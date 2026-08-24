(() => {
  'use strict';

  const ERROR_RE=/(?:error\s*(?:4\d\d|5\d\d)|server error|that[’']s an error|please try again later|bad gateway|service unavailable|too many requests|internal server error|<!doctype|<html)/i;
  const CHINESE_PROSE_RE=/(?:，|；|分鐘|小時|仍然|目前|進一步|將於|已經|對於|相關消息|賽事|球隊|球員|當局|白禮頓|阿士東|維拉|兒童|服務|加強|預防|預約|檢查|發現|將會|這些)/;
  const HIRA_RE=/[\u3040-\u309f]/;
  const HAN_RE=/[\u3400-\u9fff]/;
  const CRITICAL_FIELDS=['title','dek','summary','body','context','why','watchNext','timeLabel'];
  const PROSE_FIELDS=['dek','summary','body','context','why','watchNext'];

  const MONTH_READINGS={1:'いちがつ',2:'にがつ',3:'さんがつ',4:'しがつ',5:'ごがつ',6:'ろくがつ',7:'しちがつ',8:'はちがつ',9:'くがつ',10:'じゅうがつ',11:'じゅういちがつ',12:'じゅうにがつ'};
  const DAY_READINGS={1:'ついたち',2:'ふつか',3:'みっか',4:'よっか',5:'いつか',6:'むいか',7:'なのか',8:'ようか',9:'ここのか',10:'とおか',11:'じゅういちにち',12:'じゅうににち',13:'じゅうさんにち',14:'じゅうよっか',15:'じゅうごにち',16:'じゅうろくにち',17:'じゅうしちにち',18:'じゅうはちにち',19:'じゅうくにち',20:'はつか',21:'にじゅういちにち',22:'にじゅうににち',23:'にじゅうさんにち',24:'にじゅうよっか',25:'にじゅうごにち',26:'にじゅうろくにち',27:'にじゅうしちにち',28:'にじゅうはちにち',29:'にじゅうくにち',30:'さんじゅうにち',31:'さんじゅういちにち'};
  const DIGITS={0:'れい',1:'いち',2:'に',3:'さん',4:'よん',5:'ご',6:'ろく',7:'なな',8:'はち',9:'きゅう'};
  const MINUTES={1:'いっぷん',2:'にふん',3:'さんぷん',4:'よんぷん',5:'ごふん',6:'ろっぷん',7:'ななふん',8:'はっぷん',9:'きゅうふん'};
  const PEOPLE={1:'ひとり',2:'ふたり',4:'よにん',7:'ななにん'};
  const HOURS={0:'れいじ',4:'よじ',7:'しちじ',9:'くじ'};
  const COUNTERS={
    '本':{1:'いっぽん',2:'にほん',3:'さんぼん',4:'よんほん',5:'ごほん',6:'ろっぽん',7:'ななほん',8:'はっぽん',9:'きゅうほん',ten:'じゅっぽん'},
    '匹':{1:'いっぴき',2:'にひき',3:'さんびき',4:'よんひき',5:'ごひき',6:'ろっぴき',7:'ななひき',8:'はっぴき',9:'きゅうひき',ten:'じゅっぴき'},
    '杯':{1:'いっぱい',2:'にはい',3:'さんばい',4:'よんはい',5:'ごはい',6:'ろっぱい',7:'ななはい',8:'はっぱい',9:'きゅうはい',ten:'じゅっぱい'},
    '階':{1:'いっかい',2:'にかい',3:'さんがい',4:'よんかい',5:'ごかい',6:'ろっかい',7:'ななかい',8:'はっかい',9:'きゅうかい',ten:'じゅっかい'},
    '回':{1:'いっかい',2:'にかい',3:'さんかい',4:'よんかい',5:'ごかい',6:'ろっかい',7:'ななかい',8:'はっかい',9:'きゅうかい',ten:'じゅっかい'},
    '冊':{1:'いっさつ',2:'にさつ',3:'さんさつ',4:'よんさつ',5:'ごさつ',6:'ろくさつ',7:'ななさつ',8:'はっさつ',9:'きゅうさつ',ten:'じゅっさつ'},
    '軒':{1:'いっけん',2:'にけん',3:'さんげん',4:'よんけん',5:'ごけん',6:'ろっけん',7:'ななけん',8:'はっけん',9:'きゅうけん',ten:'じゅっけん'},
    '件':{1:'いっけん',2:'にけん',3:'さんけん',4:'よんけん',5:'ごけん',6:'ろっけん',7:'ななけん',8:'はっけん',9:'きゅうけん',ten:'じゅっけん'},
    '個':{1:'いっこ',2:'にこ',3:'さんこ',4:'よんこ',5:'ごこ',6:'ろっこ',7:'ななこ',8:'はっこ',9:'きゅうこ',ten:'じゅっこ'},
    '社':{1:'いっしゃ',2:'にしゃ',3:'さんしゃ',4:'よんしゃ',5:'ごしゃ',6:'ろくしゃ',7:'ななしゃ',8:'はっしゃ',9:'きゅうしゃ',ten:'じゅっしゃ'},
    '発':{1:'いっぱつ',2:'にはつ',3:'さんぱつ',4:'よんぱつ',5:'ごはつ',6:'ろっぱつ',7:'ななはつ',8:'はっぱつ',9:'きゅうはつ',ten:'じゅっぱつ'},
    '歳':{1:'いっさい',2:'にさい',3:'さんさい',4:'よんさい',5:'ごさい',6:'ろくさい',7:'ななさい',8:'はっさい',9:'きゅうさい',ten:'じゅっさい'},
    '節':{1:'いっせつ',2:'にせつ',3:'さんせつ',4:'よんせつ',5:'ごせつ',6:'ろくせつ',7:'ななせつ',8:'はっせつ',9:'きゅうせつ',ten:'じゅっせつ'},
    '話':{1:'いちわ',2:'にわ',3:'さんわ',4:'よんわ',5:'ごわ',6:'ろくわ',7:'ななわ',8:'はちわ',9:'きゅうわ',ten:'じゅうわ'}
  };

  function numberReading(n){n=Number(n);if(n<10)return DIGITS[n]||String(n);if(n<20)return 'じゅう'+(n===10?'':DIGITS[n-10]);if(n<100){const t=Math.floor(n/10),o=n%10;return DIGITS[t]+'じゅう'+(o?DIGITS[o]:'');}return String(n)}
  function minuteReading(n){n=Number(n);if(n<1||n>99)return null;const t=Math.floor(n/10),o=n%10;if(!o)return (t===1?'':DIGITS[t])+'じゅっぷん';return (t===0?'':t===1?'じゅう':DIGITS[t]+'じゅう')+MINUTES[o]}
  function hourReading(n){n=Number(n);if(n<0||n>24)return null;if(HOURS[n])return HOURS[n];const o=n%10;if(n>=10&&[4,7,9].includes(o)){const t=Math.floor(n/10);return (t===1?'じゅう':DIGITS[t]+'じゅう')+({4:'よじ',7:'しちじ',9:'くじ'}[o]);}return numberReading(n)+'じ'}
  function personReading(n){n=Number(n);return n>=1&&n<=99?(PEOPLE[n]||numberReading(n)+'にん'):null}
  function counterReading(n,u){n=Number(n);if(u==='歳'&&n===20)return 'はたち';const spec=COUNTERS[u];if(!spec||n<1||n>99)return null;const t=Math.floor(n/10),o=n%10;if(!t)return spec[o];if(!o)return (t===1?'':DIGITS[t])+spec.ten;return (t===1?'じゅう':DIGITS[t]+'じゅう')+spec[o]}
  function baseOf(ruby){return [...ruby.childNodes].filter(n=>n.nodeName!=='RT').map(n=>n.textContent||'').join('')}
  function visibleOf(node){if(!node)return'';if(node.nodeType===Node.TEXT_NODE)return node.textContent||'';if(node.nodeType!==Node.ELEMENT_NODE)return'';if(node.tagName==='RUBY')return baseOf(node);return [...node.childNodes].map(visibleOf).join('')}
  function beforeText(node,limit=80){let out='';for(let n=node.previousSibling;n&&out.length<limit;n=n.previousSibling)out=visibleOf(n)+out;return out.slice(-limit)}
  function afterText(node,limit=80){let out='';for(let n=node.nextSibling;n&&out.length<limit;n=n.nextSibling)out+=visibleOf(n);return out.slice(0,limit)}
  function setReading(rt,value){if(value&&rt.textContent!==value){rt.textContent=value;return true}return false}

  function fixContextualRuby(root=document){
    let changed=false;
    root.querySelectorAll('ruby').forEach(r=>{
      const rt=r.querySelector(':scope > rt');if(!rt)return;
      const base=baseOf(r),before=beforeText(r),after=afterText(r),old=rt.textContent||'';
      let m;

      // Calendar months/days, clock time, minutes, people and common counters.
      if((m=base.match(/^(\d{1,2})月$/)))changed=setReading(rt,MONTH_READINGS[Number(m[1])])||changed;
      else if(base==='月'&&(m=before.match(/(\d{1,2})$/))&&MONTH_READINGS[Number(m[1])])changed=setReading(rt,MONTH_READINGS[Number(m[1])])||changed;
      if((m=base.match(/^(\d{1,2})日$/))){const n=Number(m[1]);if(/\d{1,2}月$/.test(before))changed=setReading(rt,DAY_READINGS[n])||changed;}
      else if(base==='日'&&(m=before.match(/(\d{1,2})月(\d{1,2})$/)))changed=setReading(rt,DAY_READINGS[Number(m[2])])||changed;

      const unitMatch=base.match(/^(\d{1,2})(時|分|人|本|匹|杯|階|回|冊|軒|件|個|社|発|歳|節|話)$/);
      let n=unitMatch?Number(unitMatch[1]):null,u=unitMatch?unitMatch[2]:null;
      if(!unitMatch&&/^(時|分|人|本|匹|杯|階|回|冊|軒|件|個|社|発|歳|節|話)$/.test(base)&&(m=before.match(/(\d{1,2})$/))){n=Number(m[1]);u=base;}
      if(u==='時')changed=setReading(rt,hourReading(n))||changed;
      else if(u==='分')changed=setReading(rt,minuteReading(n))||changed;
      else if(u==='人')changed=setReading(rt,personReading(n))||changed;
      else if(u)changed=setReading(rt,counterReading(n,u))||changed;

      // 対: scores/ratios and prefixes use たい, not つい.
      if(base==='対'&&old==='つい'&&((/\d$/.test(before)&&/^\d/.test(after))||/^[ァ-ヶーA-Za-z一-龯]/.test(after)))changed=setReading(rt,'たい')||changed;

      // 後: Vた後=あと; その後 / noun+後 / loanword+後=ご in news prose.
      if(base==='後'&&old==='のち'){
        if(/た$/.test(before))changed=setReading(rt,'あと')||changed;
        else if(/その$/.test(before)||r.previousElementSibling?.tagName==='RUBY'||/[ァ-ヶーA-Za-z]$/.test(before))changed=setReading(rt,'ご')||changed;
      }

      if(base==='行方'&&old==='なめがた'&&/^(?:は|が|を|の|に|も|不明)/.test(after))changed=setReading(rt,'ゆくえ')||changed;
      if(base==='米'&&old==='こめ'&&/^(?:ドル|軍|政府|企業|市場|株|大統領|当局|連邦|議会|司法|商務|財務|国防|銀行)/.test(after))changed=setReading(rt,'べい')||changed;
      if(base==='厳'&&old.startsWith('いかめ')&&/^し(?:い|く|さ|かった|ければ)/.test(after))changed=setReading(rt,'きび')||changed;
      if(base==='数'&&old==='かず'&&(r.previousElementSibling?.tagName==='RUBY'||/[ァ-ヶーA-Za-z]$/.test(before)||/^[カか]月/.test(after)))changed=setReading(rt,'すう')||changed;
      if(base==='国'&&old==='くに'&&/(?:輸入|輸出|加盟|参加|先進|途上|対象|同盟|敵|友好)$/.test(before))changed=setReading(rt,'こく')||changed;

      // 月 as duration: 数カ月 / Nカ月 are かげつ, not がつ.
      if(base==='月'&&/[カかケヶヵ]$/.test(before)&&old==='がつ')changed=setReading(rt,'かげつ')||changed;
    });
    return changed;
  }

  function badError(value=''){return ERROR_RE.test(String(value||''))}
  function mixedProse(value=''){const t=String(value||'').trim();if(!t)return false;if(CHINESE_PROSE_RE.test(t))return true;return t.length>=28&&HAN_RE.test(t)&&!HIRA_RE.test(t)}
  function unsafeItem(item={}){return CRITICAL_FIELDS.some(k=>badError(item[k]))||PROSE_FIELDS.some(k=>mixedProse(item[k]))}
  function hasErrorPayload(value){if(typeof value==='string')return badError(value);if(Array.isArray(value))return value.some(hasErrorPayload);if(value&&typeof value==='object')return Object.values(value).some(hasErrorPayload);return false}

  function hktParts(date=new Date()){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Hong_Kong',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).formatToParts(date);return Object.fromEntries(parts.map(p=>[p.type,p.value]))}
  function nextPublicationLabel(){const p=hktParts(),minutes=Number(p.hour)*60+Number(p.minute)+Number(p.second)/60;const slots=[360,420,540,600,660,720,780,840,900,960,1020,1080,1140,1200,1260,1320,1380,1440];const next=slots.find(v=>v>minutes)??360;if(next===1440)return'24:00 HKT';return`${String(Math.floor(next/60)%24).padStart(2,'0')}:00 HKT`}
  function formatUpdated(value){const d=new Date(value||'');if(Number.isNaN(d.getTime()))return'—';const p=hktParts(d);return`${p.year}年${Number(p.month)}月${Number(p.day)}日 ${p.hour}:${p.minute} HKT`}
  function setNextPublication(){const n=document.getElementById('live-next-update');if(!n)return false;const label=nextPublicationLabel();if(n.textContent===label)return false;n.textContent=label;return true}

  function quarantineNotice(){const main=document.querySelector('main');if(!main||document.getElementById('integrity-quarantine-notice'))return;const n=document.createElement('p');n.id='integrity-quarantine-notice';n.className='notice';n.textContent='一部の記事は翻訳検証中のため一時的に保護表示しています。エラー文字列や未検証音声は表示・再生しません。';main.insertBefore(n,main.firstChild)}
  function disableAudio(container){if(!container)return;container.querySelectorAll('.audio-block,.audio-row').forEach(b=>{if(b.dataset.integrityBlocked==='1')return;b.dataset.integrityBlocked='1';b.innerHTML='<button class="audio-btn" disabled>音声再生成中</button><span class="audio-note">翻訳検証後にSupertonic 3 F3音声を再公開します</span>'})}
  function sanitizeTextNode(node,heading=false){if(!node)return false;const t=String(node.textContent||'').trim(),unsafe=badError(t)||(!heading&&mixedProse(t));if(!unsafe)return false;const replacement=heading?'翻訳を再処理中':'翻訳を再処理中です。次の同期後に自動更新されます。';if(node.textContent!==replacement)node.textContent=replacement;return true}
  function articleId(container){return container?.querySelector('.synced-audio')?.dataset?.syncArticle||''}
  function sanitizeCards(unsafeIds=new Set()){document.querySelectorAll('.lead-story,.story-card,.section-block,.live-card').forEach(card=>{let changed=false;card.querySelectorAll('h2,h3').forEach(n=>{if(sanitizeTextNode(n,true))changed=true});card.querySelectorAll('p,.lead-deck,.why-box,.watch-box').forEach(n=>{if(sanitizeTextNode(n,false))changed=true});const id=articleId(card);if(changed||(id&&unsafeIds.has(id)))disableAudio(card)})}
  function sanitizeLiveMetadata(data){const u=document.getElementById('live-updated');if(u&&(badError(u.textContent)||!u.textContent.trim()||u.textContent.trim()==='—')){const replacement=formatUpdated(data?.lastUpdated);if(u.textContent!==replacement)u.textContent=replacement}document.querySelectorAll('.live-time').forEach(n=>{if(badError(n.textContent)&&n.textContent!=='更新時刻を再確認中')n.textContent='更新時刻を再確認中'})}

  async function loadPublicationData(){const isLive=document.body?.dataset?.page==='live',path=isLive?'data/live.json':'data/latest.json';try{const r=await fetch(`${path}?integrity=${Date.now()}`,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);return await r.json()}catch(err){console.warn('publication integrity guard data check failed',err);return null}}

  async function bootGuard(){
    setNextPublication();
    if(document.getElementById('live-next-update'))setInterval(setNextPublication,30000);
    const unsafeIds=new Set();let data=null;
    const run=()=>{fixContextualRuby(document);sanitizeCards(unsafeIds);sanitizeLiveMetadata(data);setNextPublication()};
    run();
    const main=document.querySelector('main');
    if(main){let pending=false;const observer=new MutationObserver(()=>{if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;run()})});observer.observe(main,{childList:true,subtree:true,characterData:true})}
    data=await loadPublicationData();
    const items=document.body?.dataset?.page==='live'?(data?.items||[]):(data?.articles||[]);
    (Array.isArray(items)?items:[]).filter(unsafeItem).forEach(item=>unsafeIds.add(String(item.id||'')));
    if(hasErrorPayload(data)||unsafeIds.size>0)quarantineNotice();
    run();setTimeout(run,300);setTimeout(run,1200);
  }

  window.fixContextualRuby=fixContextualRuby;
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bootGuard,{once:true});else bootGuard();
})();
