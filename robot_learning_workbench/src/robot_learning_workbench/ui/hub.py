"""Explicit Hub controls on the existing Recipe/Worker page."""
from PyQt6.QtWidgets import QWidget,QHBoxLayout,QComboBox,QLineEdit,QPushButton,QCheckBox,QLabel,QMessageBox
from .jobs import BackendJob


class HubSettings(QWidget):
    def __init__(self,page):
        super().__init__(page);self.page=page;row=QHBoxLayout(self)
        self.kind=QComboBox();self.kind.addItems(['dataset','model']);self.parent_commit=QLineEdit();self.parent_commit.setPlaceholderText('업로드 대상 parent Commit')
        self.private=QCheckBox('Private Repo');self.confirm=QCheckBox('선택 artifact 업로드 승인');resolve=QPushButton('Revision 명시 Resolve')
        for w in (QLabel('Repo 종류'),self.kind,resolve):row.addWidget(w)
        if page.stage=='hub_upload':
            for w in (self.parent_commit,self.private,self.confirm):row.addWidget(w)
        self.kind.currentTextChanged.connect(lambda x:page.edit_execution('repo_type',x))
        self.parent_commit.editingFinished.connect(lambda:page.edit_execution('parent_commit',self.parent_commit.text()))
        self.private.toggled.connect(lambda x:page.edit_execution('private',x));self.confirm.toggled.connect(lambda x:page.edit_execution('confirm_upload',x))
        self.job=BackendJob(page.backend_python,self)
        self.job.finished.connect(self.resolved);resolve.clicked.connect(self.resolve)
        if page.stage=='hub_download':row.addWidget(self.private)
        create=QPushButton('새 Repo 생성 (별도 승인)');row.addWidget(create);create.clicked.connect(self.create_repo)
    def create_repo(self):
        repo=self.page.inputs['repo_id'].text();kind=self.kind.currentText();private=self.private.isChecked()
        choice=QMessageBox.question(self,'Hugging Face 원격 생성 승인',f'{kind} Repo {repo}\nPrivate={private}\n새 저장소를 생성합니다. 기존 Repo 업로드와 별도 작업입니다.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if choice!=QMessageBox.StandardButton.Yes:return
        self.job.start('hub_create',repo_id=repo,repo_type=kind,private=private,confirm=True)
    def sync(self,data):
        execution=data['execution'];self.kind.setCurrentText(execution.get('repo_type','dataset'));self.parent_commit.setText(execution.get('parent_commit',''));self.private.setChecked(execution.get('private',False));self.confirm.setChecked(False)
        if self.page.stage=='hub_upload' and execution.get('confirm_upload'):
            self.page.editor.update(lambda doc:doc['execution'].__setitem__('confirm_upload',False))
    def resolve(self):
        try:self.job.start('hub_resolve',repo_id=self.page.inputs['repo_id'].text(),repo_type=self.kind.currentText(),revision=self.page.inputs['revision'].text() or 'main')
        except Exception as error:self.page.state.setText(str(error))
    def resolved(self,result):
        if not result.get('ok'):self.page.state.setText(result['error']['message']);return
        value=result['result']
        if value.get('created'):
            self.page.state.setText('Repo 생성됨 · '+value['url']+' · Upload는 별도 승인/Resolve 필요');return
        self.page.state.setText('Remote Commit '+value['commit']+' · private='+str(value['private'])+' · 다운로드/업로드는 실행 버튼으로 별도 요청')
        if self.page.stage=='hub_download':self.page.inputs['revision'].setText(value['commit']);self.page.edit_input('revision',value['commit'])
        else:self.parent_commit.setText(value['commit']);self.page.edit_execution('parent_commit',value['commit']);self.private.setChecked(value['private'])
