// Shared by source builds and the pinned production bundle overlay.
export async function captureScreenshot(onFiles, toast) {
    if (!window.isSecureContext || !navigator.mediaDevices?.getDisplayMedia) {
        toast.info('当前连接或浏览器不支持直接截屏。可选择已有截图，或使用系统截图后按 Ctrl+V 粘贴；直接截屏需通过 HTTPS 或 localhost 打开。');
        const picker = document.createElement('input');
        picker.type = 'file';
        picker.accept = 'image/*';
        picker.onchange = () => {
            if (picker.files?.length) onFiles(Array.from(picker.files));
        };
        picker.click();
        return;
    }
    let stream;
    let video;
    try {
        stream = await navigator.mediaDevices.getDisplayMedia({video: true, audio: false});
        video = document.createElement('video');
        video.srcObject = stream;
        await video.play();
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        if (!canvas.width || !canvas.height) throw new Error('Empty capture');
        const context = canvas.getContext('2d');
        if (!context) throw new Error('Canvas unavailable');
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
        if (!blob) throw new Error('Image encoding failed');
        await onFiles([new File([blob], `screen-capture-${Date.now()}.png`, {type: 'image/png'})]);
        window.focus();
    } catch (error) {
        if (error?.name === 'NotAllowedError' || error?.name === 'AbortError') {
            toast.info('已取消截屏或未获得屏幕共享权限。可以再次点击截图，或粘贴已有截图。');
        } else {
            toast.error('截屏失败。请重试，或使用系统截图后粘贴、上传截图文件。');
        }
    } finally {
        stream?.getTracks().forEach(track => track.stop());
        if (video) video.srcObject = null;
    }
}
