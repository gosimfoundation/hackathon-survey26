"""Trusted executor completion and private diagnostics regressions."""
import os
import pytest
RUN="00000000-0000-4000-8000-000000000002"


def test_expired_participant_waits_for_trusted_result_and_cannot_decide_again(monkeypatch):
    import project_platform.executor as executor
    from challenge.challenge_workflow import GlobalDeadlineExpired
    calls=[]
    class Runtime:
        def close(self):calls.append('close')
    class Client:
        states=iter(('running','scored'))
        def call(self,action,**kwargs):
            assert action=='status'
            calls.append(action)
            return {'status':next(self.states)}
    def expire(*args,**kwargs):raise GlobalDeadlineExpired()
    monkeypatch.setattr(executor,'_execute',expire)
    monkeypatch.setattr(executor.time,'sleep',lambda _:None)
    assert executor.execute(Runtime(),Client(),{})=={'status':'scored'}
    assert calls==['close','status','status','close']


def test_private_diagnostics_bound_output_and_remove_capabilities():
    from project_platform.diagnostics import private_log,safe_code
    token='obs_'+RUN+'.'+'x'*43
    value=private_log('x'*40000+'\ncompiler: error\n'+token+' https://private.test/?token=private Bearer secret '+ 'ghs_'+'a'*40,(token,))
    assert len(value.encode())<=32768
    assert 'compiler: error' in value
    assert 'private.test' not in value and token not in value and 'Bearer secret' not in value and 'ghs_' not in value
    assert safe_code(ValueError('hidden data'))=='project_operation_failed'


def test_runtime_identity_matches_private_workspace_owner_without_extra_capabilities(tmp_path):
    from project_platform.docker_runtime import DockerWorkspace
    from project_platform.manifest import ProjectManifest
    manifest=ProjectManifest.parse({'schema_version':'observer-project-v1','image':'python@sha256:'+'a'*64,'run':['python3','agent.py']})
    root=tmp_path/'project';root.mkdir(mode=0o700)
    runtime=DockerWorkspace(root,manifest,manifest.image)
    argv=runtime._command(name='test',environment={})
    assert argv[argv.index('--user')+1]==f'{root.stat().st_uid}:{root.stat().st_gid}'
    assert '--cap-drop=ALL' in argv and '--security-opt=no-new-privileges' in argv


@pytest.mark.skipif(not os.environ.get('OBSERVER_TEST_PYTHON_IMAGE'),reason='Explicit container image required')
def test_container_build_can_write_private_workspace_with_capabilities_dropped(tmp_path):
    from project_platform.docker_runtime import DockerWorkspace
    from project_platform.manifest import ProjectManifest
    root=tmp_path/'private-project';root.mkdir(mode=0o700)
    manifest=ProjectManifest.parse({'schema_version':'observer-project-v1','image':os.environ['OBSERVER_TEST_PYTHON_IMAGE'],
      'build':[['python3','-c',"from pathlib import Path;Path('built.txt').write_text('compiled')"]],
      'run':['python3','agent.py']})
    with DockerWorkspace(root,manifest,manifest.image) as runtime:
        runtime.build()
    assert (root/'built.txt').read_text()=='compiled'


def test_agent_log_is_the_scrubbed_bounded_participant_output():
    from project_platform.diagnostics import AGENT_LOG_LIMIT, agent_log
    token='obs_'+RUN+'.'+'x'*43
    stderr=('Traceback (most recent call last):\nValueError: bad tile\n'+token+'\n'
            'calling https://platform.test/functions/v1/observer-model/v1?key=abc\nAuthorization: Bearer sk-live\n')
    value=agent_log('Collecting tabulate\nSuccessfully installed tabulate\n',stderr,(token,))
    assert value.startswith('[platform] project build output\nCollecting tabulate\n')
    assert '[platform] project stderr\nTraceback (most recent call last):\nValueError: bad tile\n' in value
    assert token not in value and 'platform.test' not in value and 'sk-live' not in value
    assert agent_log('',"only stderr\n")=='[platform] project stderr\nonly stderr\n'
    # A retained tail can begin inside a credential; that partial line is dropped.
    cut=token[20:]+' leaked-suffix\nlater line\n'
    value=agent_log('',cut,(token,),truncated=True)
    assert 'leaked-suffix' not in value and value.endswith('later line\n') and 'earlier output was truncated' in value
    # Far more than two megabytes keeps the newest output, within the bound.
    value=agent_log('build\n',''.join(f'line {i:07d}\n' for i in range(400000)),(token,))
    assert len(value.encode())<=AGENT_LOG_LIMIT+64 and value.endswith('line 0399999\n')
    assert 'line 0000000' not in value and value.startswith('[platform] earlier output was truncated\n')
