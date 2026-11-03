"""Edit the official LeRobot JSON without duplicating model parameter forms."""
from pathlib import Path
import json
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QPushButton,QLabel,QPlainTextEdit,QFileDialog
from .jobs import BackendJob


class TrainingJsonDialog(QDialog):
    def __init__(self,page):
        super().__init__(page);self.page=page;self.operation=None;self.setWindowTitle('공식 LeRobot Training JSON');self.resize(850,700)
        box=QVBoxLayout(self);row=QHBoxLayout();box.addLayout(row)
        self.model=QComboBox();row.addWidget(self.model,1);create=QPushButton('공식 기본 JSON 생성');row.addWidget(create);create.clicked.connect(self.create)
        self.text=QPlainTextEdit();self.text.setStyleSheet('background: #f4f5f8; color: #172030; font-family: monospace;');box.addWidget(self.text,1)
        self.status=QLabel('모델별 파라미터는 공식 JSON에서 편집합니다.');self.status.setWordWrap(True);box.addWidget(self.status)
        row=QHBoxLayout();box.addLayout(row);load=QPushButton('JSON 불러오기');save=QPushButton('JSON 저장 · Script에 연결');row.addWidget(load);row.addWidget(save)
        load.clicked.connect(self.choose);save.clicked.connect(self.save)
        self.job=BackendJob(page.backend_python,self);self.job.finished.connect(self.received);self.operation='catalog';self.job.start('policy_catalog')
        try:
            path=page.editor.data().get('inputs',{}).get('training_config')
            if path:self.load(page.settings.base()/path)
        except Exception as error:self.status.setText(str(error))

    def load(self,path):
        data=json.loads(Path(path).read_text())
        if not isinstance(data,dict):raise ValueError('공식 Training JSON 객체가 필요합니다.')
        self.text.setPlainText(json.dumps(data,ensure_ascii=False,indent=2));self.status.setText(str(path))

    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,'공식 Training JSON',str(self.page.workspace/'scripts/train'),'JSON (*.json)')
        if path:
            try:self.load(path)
            except Exception as error:self.status.setText(str(error))

    def create(self):
        if self.job.process.state()!=QProcess.ProcessState.NotRunning:return
        try:
            data=self.page.editor.data();dataset=data['inputs'].get('dataset');output=data['output'].get('directory')
            if not dataset or not output:raise ValueError('먼저 YAML에서 Dataset과 출력 위치를 지정하세요.')
            self.operation='create';base=self.page.settings.base()
            self.job.start('training_config',policy_type=self.model.currentText(),dataset=str((base/dataset).resolve()),output=str((base/output).resolve()))
        except Exception as error:self.status.setText(str(error))

    def received(self,response):
        if not response.get('ok'):self.status.setText(response.get('error',{}).get('message','공식 Config 조회 실패'));return
        if self.operation=='catalog':
            for row in response['result']['policies']:
                self.model.addItem(row['type']);self.model.model().item(self.model.count()-1).setEnabled(row.get('error')is None)
        else:self.text.setPlainText(json.dumps(response['result']['config'],ensure_ascii=False,indent=2))

    def save(self):
        try:
            data=json.loads(self.text.toPlainText())
            if not isinstance(data,dict)or not isinstance(data.get('policy'),dict):raise ValueError('policy를 포함한 공식 Training JSON이 필요합니다.')
            script=self.page.editor.data();base=self.page.settings.base();inputs=script.get('inputs',{})
            dataset=inputs.get('dataset');output=script.get('output',{}).get('directory');mode=script.get('execution',{}).get('mode')
            if not dataset or not output:raise ValueError('먼저 YAML에서 Dataset과 출력 위치를 지정하세요.')
            data.setdefault('dataset',{})['root']=str((base/dataset).resolve());data['output_dir']=str((base/output).resolve());data['resume']=mode=='resume'
            if mode=='finetune':
                from ..recipe import policy_model_path
                if not inputs.get('policy'):raise ValueError('finetune에는 YAML의 inputs.policy가 필요합니다.')
                data['policy']['pretrained_path']=str(policy_model_path(base/inputs['policy']))
            path,_=QFileDialog.getSaveFileName(self,'공식 JSON 새 파일로 저장',str(self.page.workspace/'scripts/train/training.json'),'JSON (*.json)')
            if not path:return
            target=Path(path).resolve()
            if not target.suffix:target=target.with_suffix('.json')
            if target.suffix.lower()!='.json':raise ValueError('JSON 파일로 저장하세요.')
            protected=('/home/hyeonhee/soarm_isaaclab','/home/hyeonhee/miniconda3','/home/hyeonhee/IsaacLab')
            if any(target.is_relative_to(p)for p in protected)or any(target.is_relative_to(self.page.workspace/p)for p in('scenes','devices','runtime','.assets')):raise ValueError('원본/자산 대신 scripts/train에 저장하세요.')
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('x')as stream:json.dump(data,stream,ensure_ascii=False,indent=2)
            self.page.settings.set_inputs({'training_config':str(target)});self.status.setText('현재 YAML의 Dataset·출력·Mode에 맞춰 JSON 저장됨 · YAML도 저장 및 적용하세요.');self.page.ready=None
        except Exception as error:self.status.setText(str(error))

    def done(self,result):
        if self.job.process.state()!=QProcess.ProcessState.NotRunning:
            self.job.stop()
            if not self.job.process.waitForFinished(1000):self.job.process.kill();self.job.process.waitForFinished(1000)
        super().done(result)
