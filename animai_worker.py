import os
import sys
import time
from playwright.sync_api import sync_playwright
from models import SessionLocal, Scene

system_state = {
    "is_running": False,
    "active_cores": 0
}

def get_runtime_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def worker_loop(core_id, project_id, target_scene_id=None):
    base_dir = get_runtime_path()
    user_data_dir = os.path.join(base_dir, "user_data")
    output_dir = os.path.join(base_dir, "output", f"project_{project_id}")
    os.makedirs(output_dir, exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            channel="chrome",
            args=['--disable-blink-features=AutomationControlled', '--start-maximized'],
            no_viewport=True,
            accept_downloads=True
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        
        session = SessionLocal()
        
        try:
            while system_state["is_running"] or target_scene_id:
                if target_scene_id:
                    scene = session.query(Scene).filter_by(id=target_scene_id, status="Pending").first()
                else:
                    scene = session.query(Scene).filter_by(project_id=project_id, status="Pending").order_by(Scene.order_index.asc()).first()
                
                if not scene:
                    break
                
                scene.status = "Processing"
                session.commit()
                scene_id = scene.id
                prompt = scene.prompt or ""
                image_path = scene.image_path if scene.image_path != "TEXT_ONLY" else None
                
                try:
                    page.goto("https://ai.tool98.com/")
                    
                    # 1. Click AnimAI Studio card
                    page.locator('a[href="/simple"]').click()
                    
                    # 2. Handle workspace modal if exists (Chào mừng bạn quay trở lại -> Tiếp tục công việc)
                    try:
                        workspace_btn = page.locator('#animaiWorkspacePickBtn')
                        workspace_btn.wait_for(state="visible", timeout=5000)
                        if workspace_btn.is_visible():
                            workspace_btn.click()
                    except:
                        pass
                        
                    # 3. Create Project
                    create_btn = page.locator('#liteProjectPickerCreateBtn')
                    create_btn.wait_for(state="visible", timeout=10000)
                    time.sleep(1)
                    create_btn.click()
                    
                    page.locator('#customPromptInput').wait_for(state="visible", timeout=5000)
                    time.sleep(1)
                    page.locator('#customPromptInput').fill(f"Scene_{scene_id}_{int(time.time())}")
                    time.sleep(0.5)
                    page.locator('#customPromptOkBtn').click()
                    
                    # 4. Wait for workspace to load and parameters to be visible
                    page.wait_for_selector('.video-resolution-select', timeout=15000)
                    time.sleep(3)
                    
                    # 5. Set Parameters
                    page.locator('.video-resolution-select').select_option('1080P')
                    time.sleep(1)
                    page.locator('.video-ratio-select').select_option('16:9')
                    time.sleep(1)
                    
                    # Duration input (need to clear first)
                    page.locator('.video-duration-input').fill('7')
                    time.sleep(1)
                    
                    page.locator('.video-model-input').select_option('gen_01')
                    time.sleep(1)
                    page.locator('.video-source-mode-select').select_option('start_end')
                    time.sleep(1)
                    
                    # 6. Fill Prompt
                    page.locator('.video-prompt-input').fill(prompt)
                    time.sleep(1)
                    
                    # 7. Add Ref
                    if image_path and os.path.exists(image_path):
                        with page.expect_file_chooser() as fc_info:
                            page.locator('.add-video-ref-btn').click()
                        file_chooser = fc_info.value
                        file_chooser.set_files(image_path)
                    
                    time.sleep(3)
                    
                    # 8. Generate Video
                    page.locator('.generate-videos-btn').click()
                    
                    # 9. Wait for Video to appear (this takes time, could be minutes)
                    # wait for `.lite-media-card` element inside `.lite-media-strip`
                    card_locator = page.locator('.lite-media-card[data-media-type="video"]').first
                    card_locator.wait_for(state="visible", timeout=300000) # 5 minutes max
                    
                    # Chờ cho video thực sự render xong (hiện ảnh bìa thumbnail có chứa link tải)
                    img_locator = card_locator.locator('.lite-video-thumb')
                    img_locator.wait_for(state="visible", timeout=300000) # Chờ thêm tối đa 5 phút nữa nếu cần
                    
                    # 10. Lấy link blob và tự tạo lệnh tải ngầm bằng Javascript
                    blob_url = img_locator.get_attribute('data-video-src')
                    
                    if not blob_url:
                        raise Exception("Không tìm thấy link blob của video để tải!")
                        
                    with page.expect_download(timeout=120000) as download_info:
                        page.evaluate(f"""
                            const a = document.createElement('a');
                            a.href = '{blob_url}';
                            a.download = 'video_download.mp4';
                            document.body.appendChild(a);
                            a.click();
                            document.body.removeChild(a);
                        """)
                        
                    download = download_info.value
                    vid_path = os.path.join(output_dir, f"scene_{scene_id}_{int(time.time())}.mp4")
                    download.save_as(vid_path)
                    
                    scene.video_path = vid_path
                    scene.status = "Completed"
                    session.commit()
                    
                except Exception as e:
                    print(f"==========================================")
                    print(f"[Core {core_id}] LỖI XỬ LÝ CẢNH {scene_id}:")
                    print(str(e))
                    print(f"==========================================")
                    scene.status = "Error"
                    scene.error_msg = str(e)
                    session.commit()
                    
                if target_scene_id:
                    break
        finally:
            session.close()
            try:
                browser.close()
            except:
                pass
