"""Explicit Hub actions read the same YAML buffer as the pipeline worker."""
from PyQt6.QtWidgets import QWidget,QHBoxLayout,QPushButton,QMessageBox
from PyQt6.QtCore import QProcess
from .jobs import BackendJob


class HubActions(QWidget):
    def __init__(self,page):
        super().__init__(page);self.page=page;self.version=None;self.operation=None
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0)
        self.resolve_button=QPushButton('Revision 조회');self.create_button=QPushButton('새 Repo 생성')
        row.addWidget(self.resolve_button);row.addWidget(self.create_button)
        self.resolve_button.clicked.connect(self.resolve);self.create_button.clicked.connect(self.create)
        self.job=BackendJob(page.backend_python,self);self.job.finished.connect(self.received)

    def arguments(self):
        data=self.page.editor.data();repo=data.get('inputs',{}).get('repo_id','')
        if not repo:raise ValueError('YAML의 inputs.repo_id를 입력하세요.')
        return data,repo,data.get('execution',{}).get('repo_type','dataset')

    def resolve(self):
        try:
            if self.job.process.state()!=QProcess.ProcessState.NotRunning:return
            data,repo,kind=self.arguments();self.version=self.page.settings.version;self.operation='resolve'
            self.job.start('hub_resolve',repo_id=repo,repo_type=kind,revision=data['inputs'].get('revision')or'main')
        except Exception as error:self.page.show_error(str(error))

    def create(self):
        try:
            if self.job.process.state()!=QProcess.ProcessState.NotRunning:return
            data,repo,kind=self.arguments();private=data.get('execution',{}).get('private',True)
            if QMessageBox.question(self,'Hub 저장소 생성',f'{kind}: {repo}\nPrivate={private}\n새 원격 저장소를 생성할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            self.operation='create';self.version=self.page.settings.version;self.job.start('hub_create',repo_id=repo,repo_type=kind,private=private,confirm=True)
        except Exception as error:self.page.show_error(str(error))

    def received(self,response):
        if not response.get('ok'):self.page.show_error(response.get('error',{}).get('message','Hub 작업 실패'));return
        result=response['result']
        if self.operation=='create':self.page.show_error('Repo 생성 완료 · '+result['url']);return
        if self.version!=self.page.settings.version:self.page.show_error('조회 중 Script가 변경되어 결과를 적용하지 않았습니다.');return
        def edit(data):
            data['inputs']['revision']=result['commit']
            if self.page.stage=='hub_upload':data['execution'].update(parent_commit=result['commit'],private=result['private'],confirm_upload=False)
        self.page.settings.update(edit);self.page.show_error('Commit '+result['commit']+' · 저장 및 적용 후 실행하세요.')
