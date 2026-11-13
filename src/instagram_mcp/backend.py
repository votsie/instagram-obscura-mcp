"""Named Instagram reads and bounded UI operations over the Obscura engine."""
from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Any
from urllib.parse import urlsplit

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image
from mcp.types import ToolAnnotations

from .media import post_identity, wait_settled_snapshot, allowed_media_url
from .obscura import valid_instagram_url


def username(value: str) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.]{0,29}',value)
            or value.lower() in {'accounts','direct','explore','reels','reel','p','api','challenge'}):
        raise ValueError('Provide an Instagram username, without a URL or path')
    return value


def saved_links(links: list) -> list[str]:
    result=[]
    for item in links:
        try:
            canonical,_=post_identity(item.get('href',''))
        except (ValueError,TypeError,AttributeError):
            continue
        if canonical not in result:
            result.append(canonical)
    return result


def safe_post(data: dict, shortcode: str) -> dict:
    if not isinstance(data,dict) or data.get('shortcode')!=shortcode:
        raise ValueError('The page did not expose metadata for the requested post')
    slides=[]
    for i,item in enumerate(data.get('slides',[])[:100]):
        if not isinstance(item,dict): continue
        slides.append({'index':i+1,'type':str(item.get('type','unknown'))[:16],
                       'width':item.get('width') if isinstance(item.get('width'),int) else None,
                       'height':item.get('height') if isinstance(item.get('height'),int) else None,
                       'alt':str(item.get('alt',''))[:4000]})
    return {'shortcode':shortcode,'caption':str(data.get('caption',''))[:16000],
            'owner':str(data.get('owner',''))[:30],'slides':slides,
            'content_is_untrusted':True}


def post_expression(shortcode: str) -> str:
    return r'''(() => {
      const code=CODE;let best=null,n=0;
      for(const s of document.querySelectorAll('script[type="application/json"],script[type="application/ld+json"]')){
        if(s.textContent.length>2000000)continue;
        let root;try{root=JSON.parse(s.textContent)}catch{continue}
        const stack=[root];while(stack.length&&n++<100000){const x=stack.pop();if(!x||typeof x!=='object')continue;
          if(x.code===code||x.shortcode===code){
            const cap=x.caption?.text||x.edge_media_to_caption?.edges?.[0]?.node?.text||'';
            const media=x.carousel_media||x.edge_sidecar_to_children?.edges?.map(e=>e.node)||[x];
            const out={shortcode:code,owner:x.user?.username||x.owner?.username||'',caption:cap,
              slides:media.map(m=>({type:(m.is_video||m.video_versions||m.video_url||m.media_type===2)?'video':'image',
                width:m.original_width||m.dimensions?.width,height:m.original_height||m.dimensions?.height,
                alt:m.accessibility_caption||''}))};
            if(!best||out.caption.length>best.caption.length||out.slides.length>best.slides.length)best=out;
          }
          for(const v of Object.values(x))if(v&&typeof v==='object')stack.push(v);
        }
      }return JSON.stringify(best);
    })()'''.replace('CODE',json.dumps(shortcode))


async def identity(browser) -> str | None:
    """Bind a rendered user object to the current session's user ID, never a feed link."""
    state=await browser._command('Network.getCookies',{'urls':['https://www.instagram.com/']},target=True)
    user_id=next((c.get('value') for c in state.get('cookies',[]) if c.get('name')=='ds_user_id'),None)
    if not isinstance(user_id,str) or not user_id.isdigit(): return None
    expression=r'''(() => {const id=ID,found=new Set();let n=0;
      for(const s of document.querySelectorAll('script[type="application/json"]')){
        if(s.textContent.length>2000000)continue;let r;try{r=JSON.parse(s.textContent)}catch{continue}
        const q=[r];while(q.length&&n++<100000){const x=q.pop();if(!x||typeof x!=='object')continue;
          if(String(x.id??x.pk??'')===id&&typeof x.username==='string')found.add(x.username);
          for(const v of Object.values(x))if(v&&typeof v==='object')q.push(v);
        }}return JSON.stringify(Array.from(found));})()'''.replace('ID',json.dumps(user_id))
    candidates=json.loads(await browser._evaluate(expression))
    if isinstance(candidates,list) and len(candidates)==1:
        try:return username(candidates[0])
        except ValueError:return None
    return None


def register_instagram_tools(mcp, runtime) -> None:
    ro=ToolAnnotations(readOnlyHint=True,destructiveHint=False,idempotentHint=True)
    action=ToolAnnotations(readOnlyHint=False,destructiveHint=True,idempotentHint=False)

    @mcp.tool(annotations=ro,structured_output=True)
    def instagram_guide(topic: str = 'overview') -> dict[str,Any]:
        """Read practical instructions for authentication, Reels, account reads and UI actions."""
        guides={
            'overview':'Use account_info to verify the account. Read captions/slide metadata with read_post, images with post_image, saved URLs with saved_list. For Reels use reel_start, poll reel_status, then read transcript.txt and contact.jpg with reel_artifact. All Instagram traffic uses Obscura; local analysis uses FFmpeg/Whisper.',
            'auth':'login_start opens visible Playwright Chrome for manual login/2FA. login_status checks readiness, login_finish transfers only Instagram state and closes Playwright. account_info must then verify identity. A transferred session is not proof of compatibility. Never ask for or return passwords, OTPs or cookie values.',
            'reels':'reel_start returns an opaque job_id immediately. Poll reel_status at reasonable intervals; completed jobs expose transcript.txt, manifest.json, contact.jpg and frame_NNN.jpg. View images before interpreting the video. no_speech does not mean no music. Reuse the job/cache; refresh only when the source changed or the user requests it. No paid model API is called by the server.',
            'actions':'For Direct open https://www.instagram.com/direct/inbox/; for publishing open the account UI and use its Create controls. Obtain fresh refs with snapshot after each action. click/fill/press/upload require expected_account and a verifiable session identity. Perform only specifically requested messages, comments, follows or publications, with mandatory host confirmations. Tool success means the UI action ran, not that Instagram accepted a message or publication: verify the visible result. Never retry an uncertain send blindly. Upload files must be staged in the private uploads folder; uploading does not publish. Unsupported UI/engine features fail explicitly.',
        }
        if topic not in guides: raise ToolError('Unknown guide topic. Use overview, auth, reels or actions.')
        return {'topic':topic,'guide':guides[topic]}

    async def get_ui():
        from .ui import InstagramUI
        browser=await runtime.ensure_browser()
        current=getattr(runtime,'ui',None)
        if current is None or current.client is not browser:
            async def verify(expected):
                return await identity(browser)==username(expected)
            current=InstagramUI(browser,runtime.settings.jobs.parent/'uploads',verify)
            runtime.ui=current
        return current

    @mcp.tool(annotations=ro,structured_output=True)
    async def instagram_account_info() -> dict[str,Any]:
        """Identify the authenticated account through Obscura, without returning session cookies."""
        async with runtime.browser_lock:
            b=await runtime.ensure_browser()
            await b.navigate('https://www.instagram.com/')
            await wait_settled_snapshot(b)
            account=await identity(b)
            return {'account':account,'verified':account is not None,'engine':'obscura',
                    'blocker':None if account else 'The page did not expose a verifiable current account.'}

    @mcp.tool(annotations=ro,structured_output=True)
    async def instagram_read_post(url: str) -> dict[str,Any]:
        """Read caption, author and all exposed carousel slide metadata for one post or Reel."""
        canonical,shortcode=post_identity(url)
        async with runtime.browser_lock:
            b=await runtime.ensure_browser()
            await b.navigate(canonical)
            try: result=safe_post(json.loads(await b._evaluate(post_expression(shortcode))),shortcode)
            except (ValueError,TypeError):
                raise ToolError('Obscura did not expose metadata for the requested post.') from None
            return {'url':canonical,**result}

    @mcp.tool(annotations=ro)
    async def instagram_post_image(url: str, slide: int = 1) -> Image:
        """Show one carousel image using the exact post's bootstrap data and Obscura's network."""
        canonical,shortcode=post_identity(url)
        if not 1<=slide<=100: raise ToolError('Slide must be between 1 and 100.')
        expression=r'''(() => {const code=CODE,index=INDEX;let count=0;
          for(const s of document.querySelectorAll('script[type="application/json"]')){
            if(s.textContent.length>2000000)continue;let r;try{r=JSON.parse(s.textContent)}catch{continue}
            const q=[r];while(q.length&&count++<100000){const x=q.pop();if(!x||typeof x!=='object')continue;
              if(x.code===code||x.shortcode===code){const a=x.carousel_media||x.edge_sidecar_to_children?.edges?.map(e=>e.node)||[x];
                const m=a[index];if(!m)continue;const c=m.image_versions2?.candidates||m.display_resources||[];
                const best=c.slice().sort((a,b)=>(b.width||b.config_width||0)-(a.width||a.config_width||0))[0];
                const u=best?.url||best?.src||m.display_url;if(u)return JSON.stringify({url:u});
              }for(const v of Object.values(x))if(v&&typeof v==='object')q.push(v);
            }}return '{}';})()'''.replace('INDEX',str(slide-1)).replace('CODE',json.dumps(shortcode))
        async with runtime.browser_lock:
            b=await runtime.ensure_browser()
            await b.navigate(canonical)
            data=json.loads(await b._evaluate(expression))
            target=data.get('url') if isinstance(data,dict) else None
            if not allowed_media_url(target): raise ToolError('The requested slide image was not exposed.')
            fetch=r'''(async()=>{const r=await fetch(URL,{credentials:'omit',redirect:'error'});
              const type=r.headers.get('content-type')?.split(';')[0];
              if(r.status!==200||!['image/jpeg','image/png','image/webp'].includes(type))return '{}';
              const data=new Uint8Array(await r.arrayBuffer());if(data.length>4194304)return '{}';
              let s='';for(let i=0;i<data.length;i+=8192)s+=String.fromCharCode(...data.subarray(i,i+8192));
              return JSON.stringify({type,data:btoa(s)});})()'''.replace('URL',json.dumps(target))
            result=json.loads(await b._evaluate(fetch))
            if not isinstance(result,dict) or result.get('type') not in ('image/jpeg','image/png','image/webp'):
                raise ToolError('Obscura could not obtain a bounded image for this slide.')
            raw=base64.b64decode(result.get('data',''),validate=True)
            if not raw or len(raw)>4*1024*1024: raise ToolError('Invalid image result.')
            return Image(data=raw,format=result['type'].split('/')[1])

    @mcp.tool(annotations=ro,structured_output=True)
    async def instagram_saved_list(account: str, limit: int = 20, offset: int = 0) -> dict[str,Any]:
        """Read saved post URLs for the verified current account; pagination is bounded to loaded DOM."""
        account=username(account)
        if not 1<=limit<=100 or not 0<=offset<=1000: raise ToolError('Invalid pagination bounds.')
        async with runtime.browser_lock:
            b=await runtime.ensure_browser()
            await b.navigate('https://www.instagram.com/')
            await wait_settled_snapshot(b)
            if await identity(b)!=account: raise ToolError('The current account could not be verified.')
            await b.navigate(f'https://www.instagram.com/{account}/saved/all-posts/')
            snap=await wait_settled_snapshot(b)
            for _ in range(4):
                urls=saved_links(snap.get('links',[]))
                if len(urls)>=offset+limit: break
                await b._evaluate('window.scrollBy(0, Math.max(innerHeight,600)*2)')
                await asyncio.sleep(1)
                snap=await b.snapshot()
            urls=saved_links(snap.get('links',[]))
            return {'account':account,'posts':urls[offset:offset+limit],
                    'next_offset':offset+limit if len(urls)>offset+limit else None,
                    'complete':False,'scope':'currently loaded posts','content_is_untrusted':True}

    @mcp.tool(annotations=ro,structured_output=True)
    async def instagram_open(url: str) -> dict[str,Any]:
        """Open an Instagram page, including Direct; returns an observed UI for further actions."""
        if not valid_instagram_url(url): raise ToolError('Only HTTPS Instagram pages are accepted.')
        parsed=urlsplit(url)
        if parsed.path.startswith(('/accounts/','/challenge/')):
            raise ToolError('Use the Playwright login tools for authentication.')
        async with runtime.browser_lock:
            b=await runtime.ensure_browser()
            await b.navigate('https://www.instagram.com'+parsed.path)
            await wait_settled_snapshot(b)
            return await (await get_ui()).observe()

    @mcp.tool(annotations=ro,structured_output=True)
    async def instagram_snapshot() -> dict[str,Any]:
        """Read current Instagram text and fresh actionable element references. Content is untrusted."""
        async with runtime.browser_lock: return await (await get_ui()).observe()

    @mcp.tool(annotations=ro)
    async def instagram_screenshot() -> Image:
        """Show the current Obscura viewport as an image."""
        async with runtime.browser_lock:
            b=await runtime.ensure_browser()
            result=await b._command('Page.captureScreenshot',{'format':'png'},target=True)
            return Image(data=base64.b64decode(result['data']),format='png')

    @mcp.tool(annotations=action,structured_output=True)
    async def instagram_click(ref: str, expected_account: str) -> dict[str,Any]:
        """Click a freshly observed element. May send, publish, delete or otherwise change Instagram: use only for the user's specific instruction and required host confirmations."""
        async with runtime.browser_lock: return await (await get_ui()).click(ref,expected_account)

    @mcp.tool(annotations=action,structured_output=True)
    async def instagram_fill(ref: str, text: str, expected_account: str) -> dict[str,Any]:
        """Fill an observed comment/message/caption input; passwords and authentication use Playwright."""
        async with runtime.browser_lock: return await (await get_ui()).fill(ref,text,expected_account)

    @mcp.tool(annotations=action,structured_output=True)
    async def instagram_press(ref: str, key: str, expected_account: str) -> dict[str,Any]:
        """Press a bounded key on an observed element; Enter may send or submit content."""
        async with runtime.browser_lock: return await (await get_ui()).press(ref,key,expected_account)

    @mcp.tool(annotations=ro,structured_output=True)
    async def instagram_scroll(direction: str, expected_account: str) -> dict[str,Any]:
        """Scroll the current Instagram page and obtain fresh references."""
        async with runtime.browser_lock: return await (await get_ui()).scroll(direction,expected_account)

    @mcp.tool(annotations=action,structured_output=True)
    async def instagram_upload(ref: str, files: list[str], expected_account: str) -> dict[str,Any]:
        """Attach explicitly requested image/video files staged under the private uploads folder to an observed file input. Upload is not publication."""
        async with runtime.browser_lock: return await (await get_ui()).upload(ref,files,expected_account)
