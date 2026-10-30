"""Explicit motion limits and session-local on-site approval; no device imports."""
import json
from PyQt6.QtWidgets import QWidget,QDialog,QVBoxLayout,QFormLayout,QLabel,QDoubleSpinBox,QDialogButtonBox,QPlainTextEdit,QCheckBox


class MotionLimits(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);form=QFormLayout(self);form.setContentsMargins(0,0,0,0);self.fields={}
        for key,label in(('max_command_step_rad','목표 변화 제한 (rad/주기)'),('max_follow_error_rad','추종 오차 제한 (rad)')):
            field=QDoubleSpinBox();field.setDecimals(4);field.setRange(0,6.3);field.setSingleStep(.01);field.setSpecialValueText('미설정');form.addRow(label,field);self.fields[key]=field
    def load(self,settings):
        for key,field in self.fields.items():
            previous=field.blockSignals(True)
            try:field.setValue(settings.get(key)or 0)
            finally:field.blockSignals(previous)
    def values(self):
        result={key:field.value()for key,field in self.fields.items()}
        if not any(result.values()):return {}
        if not all(result.values()):raise ValueError('목표 변화와 추종 오차 제한을 모두 입력하세요.')
        return result


def request_limits(parent,current):
    keys=('max_command_step_rad','max_follow_error_rad')
    if all(current.get(k)for k in keys):return {k:current[k]for k in keys}
    dialog=QDialog(parent);parent.approval_dialog=dialog;dialog.setWindowTitle('Teleoperation 이동 제한');box=QVBoxLayout(dialog)
    note=QLabel('현재 로봇에 사용할 목표 변화·추종 오차 제한을 입력하세요.\n이 값은 소프트웨어 중단 기준이며 물리 안전 범위 승인이 아닙니다.\n다음 화면에서 현재 자세·방향·범위와 초기 Goal 정렬을 직접 확인합니다.');note.setWordWrap(True);box.addWidget(note)
    limits=MotionLimits();limits.load(current);box.addWidget(limits);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);box.addWidget(buttons)
    def changed():buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(all(field.value()>0 for field in limits.fields.values()))
    for field in limits.fields.values():field.valueChanged.connect(changed)
    changed();buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
    try:return limits.values()if dialog.exec()==QDialog.DialogCode.Accepted and parent.isVisible()else None
    finally:parent.approval_dialog=None


def approve(parent,proposal):
    if not parent.isVisible():return None
    dialog=QDialog(parent);parent.approval_dialog=dialog;dialog.setWindowTitle('현장 감독 Teleoperation 승인');box=QVBoxLayout(dialog)
    label=QLabel('Leader가 실제 Follower를 제어합니다. 현재 Model/Precision Mapping·방향·관절 범위를 현장에서 확인하세요.\n승인 후 Leader Torque를 해제하고, 미구동 Follower 축의 Goal을 현재 위치에 정렬한 뒤 Torque를 켭니다.\n중단은 새 Goal을 차단하고 Torque를 유지합니다. 자동 Home은 없습니다.');label.setWordWrap(True);box.addWidget(label)
    detail=QPlainTextEdit(json.dumps(proposal,ensure_ascii=False,indent=2));detail.setReadOnly(True);box.addWidget(detail);checks={}
    for key,text in(('supervised','현장에서 직접 감독합니다'),('clear','충돌 위험과 주변 장애물을 확인했습니다'),('stop_ready','즉시 전원 차단 수단이 준비됐습니다'),('direction_checked','이 Model/Precision Mapping의 Leader/Follower 방향을 확인했습니다'),('ranges_checked','현재 관절·명령 범위와 표시된 이동 제한을 확인했습니다'),('preserve_torque','중단 시 Torque 유지 정책을 확인했습니다'),('initialize_goal','표시된 Leader Torque 해제·Follower Goal 정렬 및 활성화를 승인합니다')):
        check=QCheckBox(text);checks[key]=check;box.addWidget(check)
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);box.addWidget(buttons);buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
    for check in checks.values():check.toggled.connect(lambda:buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(all(c.isChecked()for c in checks.values())))
    buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
    try:return {'proposal_sha256':proposal['sha256'],**{k:c.isChecked()for k,c in checks.items()}}if dialog.exec()==QDialog.DialogCode.Accepted and parent.isVisible()else None
    finally:parent.approval_dialog=None
