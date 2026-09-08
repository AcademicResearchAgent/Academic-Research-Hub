set -euo pipefail
export PATH=/home/ubuntu/haudi-hermes/runtime/bin:/home/ubuntu/haudi-hermes/runtime/node/bin:$PATH
agent-browser --session haudi-attachment-v4 eval 'window.__capturePickerCount=0;window.__originalInputClick=HTMLInputElement.prototype.click;HTMLInputElement.prototype.click=function(){if(this.type==="file"&&this.accept==="image/*"){window.__capturePickerCount++;return;}return window.__originalInputClick.call(this);};JSON.stringify({secure:window.isSecureContext})'
agent-browser --session haudi-attachment-v4 click @e4
agent-browser --session haudi-attachment-v4 eval 'if(window.__capturePickerCount!==1||!document.body.innerText.includes("当前连接或浏览器不支持直接截屏"))throw new Error("Screenshot fallback did not activate");HTMLInputElement.prototype.click=window.__originalInputClick;JSON.stringify({screenshotButton:"pass",filePickerRequested:true,visibleExplanation:true})'
agent-browser --session haudi-attachment-v4 close
