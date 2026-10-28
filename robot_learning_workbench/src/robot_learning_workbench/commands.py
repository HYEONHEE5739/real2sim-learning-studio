"""Episode-boundary IPC routing/acknowledgements; no physics or device ownership."""


def control_commands(rows,state,events,*,tick,episode_id,env_index=0):
    """Execute already claimed IPC commands once at the current control boundary."""
    for row in rows:
        if row.get('episode_id',episode_id)!=episode_id or row.get('env_index',env_index)!=env_index:raise ValueError('Stale command target')
        kind=row['kind'];payload=row.get('payload',{})
        if state.get('inactive') and kind!='cancel':
            events({'kind':'command_ack','payload':{'command_id':row['command_id'],'status':'rejected','reason':'Episode already closed; only cancel is supported during reset cooldown'}})
            continue
        if kind=='cancel':state['cancelled']=True
        elif kind=='pause':state['paused']=True
        elif kind=='resume':state['paused']=False
        elif kind=='step':
            if state['steps']:raise ValueError('A step command is already in progress')
            state['steps']=payload['count'];state['paused']=True;state['step_command']=row['command_id']
            continue
        elif kind=='skip':state['skipped']=True
        elif kind=='save':state['save']=True
        elif kind=='discard':state['discard']=True
        elif kind=='mark':
            if payload['event']!='grasp' or not 0<payload['frame']<=tick:raise ValueError('Invalid manual grasp boundary')
            state['marks'].append(payload['frame'])
        else:raise ValueError('Unsupported workflow command')
        events({'kind':'command_ack','payload':{'command_id':row['command_id'],'status':'completed','applied_tick':tick}})



def step_completed(state,events,tick):
    if state['steps']:
        state['steps']-=1
        if not state['steps']:
            events({'kind':'command_ack','payload':{'command_id':state.pop('step_command'),'status':'completed','applied_tick':tick}})



def command_channels(commands,events,count,*,vector=False):
    """Route explicit env commands; vector pause/resume applies to the whole scene."""
    import threading
    lock=threading.RLock();pending=[[] for _ in range(count)];cancel=None;acked=set();stopping=threading.Event();paused=False
    def send(event):
        with lock:
            if event['kind']=='command_ack':
                cid=event['payload']['command_id']
                if cid in acked:return
                acked.add(cid)
            events(event)
    def refresh():
        nonlocal cancel,paused
        with lock:
            for row in commands():
                if row['kind']=='cancel':cancel={k:v for k,v in row.items() if k not in ('env_index','episode_id')}
                elif vector and row['kind'] in ('pause','resume'):
                    paused=row['kind']=='pause';global_row={k:v for k,v in row.items() if k not in ('env_index','episode_id')}
                    for queue in pending:queue.append(global_row)
                elif vector and row['kind']=='step':send({'kind':'command_ack','payload':{'command_id':row['command_id'],'status':'rejected','reason':'Official vector physics steps the whole scene; per-env single-step is unsupported'}})
                elif type(row.get('env_index')) is int and 0<=row['env_index']<count:pending[row['env_index']].append(row)
                else:send({'kind':'command_ack','payload':{'command_id':row['command_id'],'status':'rejected','reason':'Explicit active env_index required'}})
    def poll(index):
        with lock:
            if stopping.is_set():raise RuntimeError('Sibling environment failed; cooperative interruption')
            refresh();rows=pending[index];pending[index]=[]
            if cancel is not None:rows=[cancel,*rows]
            return rows
    send.stop=stopping.set;send.refresh=refresh;send.paused=lambda:paused
    send.cancelled=lambda:cancel is not None
    send.ack_cancel=lambda:send({'kind':'command_ack','payload':{'command_id':cancel['command_id'],'status':'completed'}})
    return [lambda i=i:poll(i) for i in range(count)],send

