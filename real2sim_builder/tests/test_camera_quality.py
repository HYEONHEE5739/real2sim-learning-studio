from real2sim_builder.validation import camera_quality


def observations(wrist=.1,side=.1):
    return [{'image_id':'w1','camera_type':'wrist','q_measured':[0]*6,'mae':wrist},
            {'image_id':'w2','camera_type':'wrist','q_measured':[.1]*6,'mae':wrist},
            {'image_id':'s','camera_type':'side','mae':side},
            {'image_id':'p','camera_type':'external','mae':0.}]


def criteria():
    return {role:{'evidence':['explicit test tolerance, not physical certification'],
                  'metrics':{'mae':{'max':.2}}}for role in ('wrist','side')}


def test_each_robot_camera_must_pass_independently():
    assert camera_quality(observations(wrist=.3),criteria())['status']=='NOT_MET'
    assert camera_quality(observations(side=.3),criteria())['status']=='NOT_MET'
    assert camera_quality(observations(),criteria())['status']=='CRITERIA_MET_UNVERIFIED'


def test_no_invented_threshold_or_multiple_q():
    assert camera_quality(observations(),{})['status']=='NOT_VERIFIED'
    rows=observations();rows[1]['q_measured']=[0]*6
    assert camera_quality(rows,criteria())['status']=='NOT_VERIFIED'
    assert camera_quality([observations()[-1]],criteria())['status']=='NOT_VERIFIED'
    rows=observations();del rows[0]['mae']
    assert camera_quality(rows,criteria())['status']=='NOT_VERIFIED'
