import pytest
import base64
import json
from mcp import Client
from instagram_mcp.backend import username, saved_links, safe_post
from instagram_mcp.server import Runtime, create_server


@pytest.mark.asyncio
async def test_reads_bind_session_identity_and_refuse_other_saved_account(tmp_path, monkeypatch):
    import instagram_mcp.backend as backend
    class Browser:
        def __init__(self): self.urls=[]; self.accounts=['owner']
        async def close(self): pass
        async def navigate(self,url): self.urls.append(url)
        async def _command(self,*args,**kwargs):
            return {'cookies':[{'name':'ds_user_id','value':'123'},
                               {'name':'sessionid','value':'private-cookie'}]}
        async def _evaluate(self,expression):
            if 'const id=' in expression: return json.dumps(self.accounts)
            return json.dumps({'shortcode':'ABC','caption':'caption','owner':'author','slides':[]})
    async def settled(browser):
        return {'links':[{'href':'https://www.instagram.com/p/ABC/'},
                         {'href':'https://www.instagram.com/p/DEF/'}]}
    monkeypatch.setattr(backend,'wait_settled_snapshot',settled)
    runtime=Runtime.for_test(tmp_path); browser=Browser();runtime.browser=browser
    async with Client(create_server(runtime)) as client:
        result=await client.call_tool('instagram_account_info',{})
        assert result.structured_content['account']=='owner'
        assert 'private-cookie' not in str(result)
        result=await client.call_tool('instagram_saved_list',{'account':'other','limit':1})
        assert result.is_error and not any('/saved/' in url for url in browser.urls)
        result=await client.call_tool('instagram_saved_list',{'account':'owner','limit':1})
        assert result.structured_content['posts']==['https://www.instagram.com/p/ABC/']
        assert result.structured_content['next_offset']==1
        assert result.structured_content['complete'] is False
        result=await client.call_tool('instagram_read_post',{'url':'https://www.instagram.com/p/ABC/?tracking=private'})
        assert result.structured_content['caption']=='caption'
        assert result.structured_content['url']=='https://www.instagram.com/p/ABC/'
        result=await client.call_tool('instagram_read_post',{'url':'https://www.instagram.com/p/OTHER/'})
        assert result.is_error
        browser.accounts=['owner','ambiguous']
        result=await client.call_tool('instagram_account_info',{})
        assert result.structured_content['verified'] is False


def test_username_rejects_paths_and_reserved_routes():
    assert username('some.user_1') == 'some.user_1'
    for value in ('../secret', 'a/b', 'accounts', '', 'a'*31):
        with pytest.raises(ValueError):
            username(value)


def test_saved_deduplicates_and_rejects_external_links():
    links=[{'href':'https://www.instagram.com/p/ABC/?secret=1'},
           {'href':'https://www.instagram.com/p/ABC/'},
           {'href':'https://evil.test/p/ABC/'}]
    assert saved_links(links)==['https://www.instagram.com/p/ABC/']


def test_post_result_drops_signed_urls_and_unknown_fields():
    value={'shortcode':'ABC','caption':'hello','owner':'owner',
           'slides':[{'type':'video','width':720,'height':1280,'url':'https://cdn.test/?secret=1'}],
           'sessionid':'never return'}
    result=safe_post(value,'ABC')
    assert result['caption']=='hello'
    assert 'secret' not in str(result) and 'sessionid' not in str(result)


def test_post_result_requires_selected_shortcode():
    with pytest.raises(ValueError):
        safe_post({'shortcode':'OTHER'},'ABC')


@pytest.mark.asyncio
async def test_mcp_image_preserves_shortcode_template_words(tmp_path):
    class Browser:
        def __init__(self): self.expressions=[]
        async def navigate(self,url): pass
        async def close(self): pass
        async def _evaluate(self,expr):
            self.expressions.append(expr)
            if 'const code=' in expr:return json.dumps({'url':'https://x.cdninstagram.com/image.jpg'})
            return json.dumps({'type':'image/jpeg','data':base64.b64encode(b'jpeg-fixture').decode()})
    runtime=Runtime.for_test(tmp_path)
    runtime.browser=Browser()
    async with Client(create_server(runtime)) as client:
        result=await client.call_tool('instagram_post_image',{'url':'https://www.instagram.com/p/AbINDEX123/'})
        assert not result.is_error and result.content[0].type=='image'
        assert '"AbINDEX123"' in runtime.browser.expressions[0]


@pytest.mark.asyncio
async def test_mcp_annotations_do_not_label_actions_as_safe(tmp_path):
    runtime=Runtime.for_test(tmp_path)
    async with Client(create_server(runtime)) as client:
        tools={t.name:t for t in (await client.list_tools()).tools}
        for name in ('instagram_click','instagram_press','instagram_upload'):
            assert tools[name].annotations.read_only_hint is False
            assert tools[name].annotations.destructive_hint is True
        assert tools['instagram_read_post'].annotations.read_only_hint is True


@pytest.mark.asyncio
async def test_ui_tools_preserve_expected_account_and_use_fixed_methods(tmp_path,monkeypatch):
    import instagram_mcp.ui as ui_module
    calls=[]
    class Browser:
        async def close(self): pass
    class UI:
        def __init__(self,client,*_):self.client=client
        async def observe(self):return {'elements':[]}
        async def click(self,*args):calls.append(('click',args));return {'state':'observed'}
        async def fill(self,*args):calls.append(('fill',args));return {'state':'observed'}
        async def press(self,*args):calls.append(('press',args));return {'state':'observed'}
        async def scroll(self,*args):calls.append(('scroll',args));return {'state':'observed'}
        async def upload(self,*args):calls.append(('upload',args));return {'state':'observed'}
    monkeypatch.setattr(ui_module,'InstagramUI',UI)
    runtime=Runtime.for_test(tmp_path);runtime.browser=Browser()
    async with Client(create_server(runtime)) as client:
        requests=[('click',{'ref':'r1'}),('fill',{'ref':'r2','text':'draft'}),
                  ('press',{'ref':'r2','key':'Tab'}),('scroll',{'direction':'down'}),
                  ('upload',{'ref':'r3','files':['draft.mp4']})]
        for name,args in requests:
            result=await client.call_tool('instagram_'+name,{**args,'expected_account':'owner'})
            assert not result.is_error
        assert len(calls)==5
        assert all(args[-1]=='owner' for _,args in calls)
