const tg = window.Telegram.WebApp;
tg.expand();
tg.enableClosingConfirmation();

const initData = tg.initData;
let currentConv = null;

const chatEl = document.getElementById(\'chat\');
const inputEl = document.getElementById(\'input\');
const sendBtn = document.getElementById(\'send\');
const convListEl = document.getElementById(\'convList\');
const modelSelect = document.getElementById(\'modelSelect\');
const newChatBtn = document.getElementById(\'newChat\');

function scrollBottom(){
  chatEl.scrollTop = chatEl.scrollHeight;
}

function render(msgs){
  chatEl.innerHTML = "";
  if(msgs.length === 0){
    chatEl.innerHTML = `<div style="text-align:center;color:#888;margin-top:40px;">سلام! 👋 پیام خودت رو بنویس تا شروع کنیم ✨</div>`;
    return;
  }
  msgs.forEach(m => {
    const div = document.createElement(\'div\');
    div.className = \'msg \' + m[0];
    // m[0] = role, m[1] = content
    div.textContent = m[1];
    chatEl.appendChild(div);
  });
  scrollBottom();
}

async function loadConvs(){
  try{
    const res = await fetch(`/api/conversations?initData=${encodeURIComponent(initData)}`);
    if(!res.ok) return;
    const data = await res.json();
    convListEl.innerHTML = "";
    data.forEach(c => {
      const id = c[0], title = c[1];
      const d = document.createElement(\'div\');
      d.className = \'conv\' + (id === currentConv ? \' active\' : \'\');
      d.textContent = title || "چت جدید";
      d.onclick = async () => {
        currentConv = id;
        await loadHistory(id);
        loadConvs();
      };
      // حذف با کلیک راست / نگه داشتن
      d.oncontextmenu = async (e) => {
        e.preventDefault();
        if(confirm("حذف این چت؟")){
          await fetch(\'/api/conversations/delete\', {
            method: \'POST\',
            headers: {\'Content-Type\': \'application/json\'},
            body: JSON.stringify({initData, conversation_id: id})
          });
          currentConv = null;
          chatEl.innerHTML = "";
          loadConvs();
        }
      };
      convListEl.appendChild(d);
    });
  }catch(e){ console.error(e); }
}

async function loadHistory(convId){
  try{
    const r = await fetch(`/api/history/${convId}?initData=${encodeURIComponent(initData)}`);
    if(!r.ok) return;
    const msgs = await r.json();
    render(msgs);
  }catch(e){ console.error(e); }
}

async function sendMessage(){
  const text = inputEl.value.trim();
  if(!text) return;
  const model = modelSelect.value;
  
  // نمایش پیام کاربر فوری
  const userDiv = document.createElement(\'div\');
  userDiv.className = \'msg user\';
  userDiv.textContent = text;
  chatEl.appendChild(userDiv);
  scrollBottom();
  inputEl.value = "";
  sendBtn.disabled = true;
  sendBtn.textContent = "⏳...";

  // پیام در حال تایپ
  const typing = document.createElement(\'div\');
  typing.className = \'msg assistant\';
  typing.textContent = "✨ در حال نوشتن...";
  typing.id = "typing";
  chatEl.appendChild(typing);
  scrollBottom();

  try{
    const res = await fetch(\'/api/chat\', {
      method: \'POST\',
      headers: {\'Content-Type\': \'application/json\'},
      body: JSON.stringify({initData, message: text, model, conversation_id: currentConv})
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || "خطا");
    
    currentConv = data.conversation_id;
    document.getElementById(\'typing\')?.remove();
    
    const botDiv = document.createElement(\'div\');
    botDiv.className = \'msg assistant\';
    botDiv.textContent = data.answer;
    chatEl.appendChild(botDiv);
    scrollBottom();
    loadConvs();
  }catch(err){
    document.getElementById(\'typing\')?.remove();
    const errDiv = document.createElement(\'div\');
    errDiv.className = \'msg assistant\';
    errDiv.style.color = "#ff6b6b";
    errDiv.textContent = "❌ خطا: " + err.message;
    chatEl.appendChild(errDiv);
  }finally{
    sendBtn.disabled = false;
    sendBtn.textContent = "ارسال";
  }
}

sendBtn.onclick = sendMessage;
inputEl.addEventListener(\'keydown\', e => {
  if(e.key === \'Enter\' && !e.shiftKey){
    e.preventDefault();
    sendMessage();
  }
});

newChatBtn.onclick = () => {
  currentConv = null;
  chatEl.innerHTML = `<div style="text-align:center;color:#888;margin-top:40px;">چت جدید ✨ پیام بده!</div>`;
  loadConvs();
};

// لود اولیه
loadConvs();
