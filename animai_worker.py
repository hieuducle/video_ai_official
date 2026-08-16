import os
import sys
import time
import urllib.request
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

def check_and_download_completed_scenes(k, scenes, page, output_dir, session):
    for j in range(k):
        scene = scenes[j]
        if scene.status != "Processing":
            continue
        try:
            card_idx = k - 1 - j
            target_item = page.locator('.lite-media-strip').locator('.lite-media-card, .lite-media-placeholder-preview').nth(card_idx)
            
            # Kiểm tra lỗi render từ AI Studio
            err_locator = target_item.locator('.lite-media-error, .lite-error-badge')
            if err_locator.is_visible():
                print(f"[Queue Mode] Scene {scene.id} bị lỗi render từ phía AI Studio!")
                scene.status = "Error"
                scene.error_msg = "Lỗi render từ AI Studio"
                session.commit()
                continue
                
            img_locator = target_item.locator('.lite-video-thumb')
            if img_locator.is_visible():
                blob_url = img_locator.get_attribute('data-video-src')
                if blob_url:
                    print(f"[Queue Mode] Phát hiện Scene {scene.id} đã render xong sớm! Đang tải về ngay...")
                    with page.expect_download(timeout=60000) as download_info:
                        page.evaluate(f"""
                            const a = document.createElement('a');
                            a.href = '{blob_url}';
                            a.download = 'video_download_{scene.id}.mp4';
                            document.body.appendChild(a);
                            a.click();
                            document.body.removeChild(a);
                        """)
                    download = download_info.value
                    vid_path = os.path.join(output_dir, f"scene_{scene.id}_{int(time.time())}.mp4")
                    download.save_as(vid_path)
                    
                    scene.video_path = vid_path
                    scene.status = "Completed"
                    session.commit()
                    print(f"[Queue Mode] >>> ĐÃ HOÀN THÀNH & TẢI XONG SỚM Scene {scene.id} -> {vid_path}")
        except Exception:
            pass

def run_single_tab_queue(core_id, project_id, source_mode, ai_model, output_dir, session, page):
    try:
        scenes = session.query(Scene).filter_by(project_id=project_id, status="Pending").order_by(Scene.order_index.asc()).all()
        if not scenes:
            print(f"[Core {core_id}] [Queue Mode] Không tìm thấy cảnh nào ở trạng thái Pending cho dự án {project_id}!")
            return
            
        print(f"[Core {core_id}] Bắt đầu chế độ 1 Tab (Queue Mode) tạo liên tiếp cho {len(scenes)} cảnh...")
        
        print(f"[Core {core_id}] Đang truy cập trực tiếp https://ai.tool98.com/simple ...")
        page.goto("https://ai.tool98.com/simple", wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
        
        try:
            workspace_btn = page.locator('#animaiWorkspacePickBtn')
            workspace_btn.wait_for(state="visible", timeout=5000)
            if workspace_btn.is_visible():
                print(f"[Core {core_id}] Nhận diện modal chọn workspace, bấm Tiếp tục...")
                workspace_btn.click()
                time.sleep(1)
        except:
            pass
            
        print(f"[Core {core_id}] Bấm nút Tạo Dự Án Mới (#liteProjectPickerCreateBtn)...")
        create_btn = page.locator('#liteProjectPickerCreateBtn')
        create_btn.wait_for(state="visible", timeout=15000)
        time.sleep(1)
        create_btn.click()
        
        print(f"[Core {core_id}] Điền tên dự án trong Prompt modal...")
        page.locator('#customPromptInput').wait_for(state="visible", timeout=10000)
        time.sleep(1)
        page.locator('#customPromptInput').fill(f"Queue_{project_id}_{int(time.time())}")
        time.sleep(0.5)
        page.locator('#customPromptOkBtn').click()
        
        print(f"[Core {core_id}] Đang chờ tải giao diện studio...")
        page.wait_for_selector('.video-resolution-select', timeout=60000)
        time.sleep(3)
        
        print(f"[Core {core_id}] Thiết lập thông số ban đầu (1080P, 16:9, {ai_model})...")
        page.locator('.video-resolution-select').select_option('1080P')
        time.sleep(0.5)
        try:
            page.locator('.video-quality-select').select_option('low')
            time.sleep(0.5)
        except Exception:
            pass
        page.locator('.video-ratio-select').select_option('16:9')
        time.sleep(0.5)
        page.locator('.video-model-input').select_option(ai_model)
        time.sleep(0.5)
        page.locator('.video-source-mode-select').select_option(source_mode)
        time.sleep(2.5) # Chờ DOM của Studio render ổn định hoàn toàn sau khi đổi chế độ/thông số
        page.wait_for_selector('.video-prompt-input', state="visible", timeout=15000)
        
        # GIAI ĐOẠN 1: Gửi liên tiếp từng cảnh vào hàng đợi 1 Tab (và kiểm tra tải ngay cảnh nào xong)
        for i, scene in enumerate(scenes):
            if not system_state["is_running"]:
                print(f"[Queue Mode] Dừng gửi thêm cảnh theo yêu cầu từ người dùng.")
                break
                
            print(f"[Queue Mode] --- Chuẩn bị cảnh {i+1}/{len(scenes)} (ID: {scene.id}) ---")
            scene.status = "Processing"
            session.commit()
            
            # 1. Xóa tất cả các ảnh ref cũ của cảnh trước (nếu có)
            while True:
                remove_btn = page.locator('.lite-ref-chip-remove').first
                if remove_btn.is_visible():
                    try:
                        remove_btn.click()
                        time.sleep(0.5)
                    except:
                        break
                else:
                    break
                    
            # 2. Điền Prompt (có retry chống lỗi DOM re-render ở cảnh đầu tiên)
            prompt_text = scene.prompt or ""
            for attempt in range(3):
                try:
                    prompt_input = page.locator('.video-prompt-input')
                    prompt_input.wait_for(state="visible", timeout=5000)
                    prompt_input.click()
                    time.sleep(0.3)
                    prompt_input.fill(prompt_text)
                    break
                except Exception as e:
                    print(f"[Queue Mode] Thử điền prompt lần {attempt+1} cho Scene {scene.id} gặp lỗi DOM ({str(e)}), thử lại...")
                    time.sleep(1)
            time.sleep(0.5)
            
            # 3. Điền Số giây
            duration_val = getattr(scene, 'duration', 7) or 7
            duration_val = max(1, min(13, int(duration_val)))
            page.locator('.video-duration-input').fill(str(duration_val))
            time.sleep(0.5)
            
            # 4. Upload ảnh ref cho cảnh hiện tại (có retry chống lỗi interface object state cached)
            image_path = scene.image_path if scene.image_path != "TEXT_ONLY" else None
            if image_path and os.path.exists(image_path):
                print(f"[Queue Mode] Uploading ref image: {image_path}")
                for attempt in range(3):
                    try:
                        time.sleep(0.5)
                        with page.expect_file_chooser(timeout=10000) as fc_info:
                            page.locator('.add-video-ref-btn').click()
                        file_chooser = fc_info.value
                        file_chooser.set_files(image_path)
                        break
                    except Exception as e:
                        print(f"[Queue Mode] Thử upload ref image lần {attempt+1} cho Scene {scene.id} gặp lỗi DOM ({str(e)}), thử lại...")
                        time.sleep(1.5)
                time.sleep(3)
                
            # 5. Bấm tạo video
            print(f"[Queue Mode] Bấm nút Tạo Video cho Scene {scene.id}...")
            page.locator('.generate-videos-btn').click()
            time.sleep(2)
            
            # 6. Chờ cảnh vừa bấm thoát khỏi trạng thái "Hàng đợi" (và quét tải về các video đã render xong trước đó)
            print(f"[Queue Mode] Chờ Scene {scene.id} vào render (thoát trạng thái Hàng đợi)...")
            while system_state["is_running"]:
                # Kiểm tra & tải ngay bất kỳ video nào (trong số các cảnh từ 0 -> i) vừa xong sớm
                check_and_download_completed_scenes(i + 1, scenes, page, output_dir, session)
                
                total_items = page.locator('.lite-media-strip').locator('.lite-media-card, .lite-media-placeholder-preview').count()
                if total_items >= i + 1:
                    first_item = page.locator('.lite-media-strip').locator('.lite-media-card, .lite-media-placeholder-preview').first
                    if first_item.locator('.lite-video-thumb').is_visible():
                        print(f"[Queue Mode] Scene {scene.id} đã hoàn tất render sớm!")
                        break
                    first_percent = first_item.locator('.lite-media-placeholder-percent')
                    if first_percent.is_visible():
                        txt = first_percent.inner_text().strip()
                        if "%" in txt:
                            print(f"[Queue Mode] Scene {scene.id} đã vào render ({txt}), tiếp tục cảnh tiếp theo...")
                            break
                time.sleep(2)
                
        # GIAI ĐOẠN 2: Giám sát liên tục và tải ngay lập tức bất kỳ video nào vừa render xong
        print(f"[Core {core_id}] Đã gửi đủ {len(scenes)} cảnh. Bắt đầu giám sát liên tục và tải ngay bất kỳ video nào render xong...")
        while system_state["is_running"]:
            pending_or_proc = [s for s in scenes if s.status == "Processing"]
            if not pending_or_proc:
                print(f"[Core {core_id}] Tất cả {len(scenes)} cảnh đã được render và tải về hoàn tất!")
                break
                
            check_and_download_completed_scenes(len(scenes), scenes, page, output_dir, session)
            time.sleep(3)
    except Exception as e:
        print(f"==========================================")
        print(f"[Core {core_id}] LỖI TỔNG CHẾ ĐỘ 1 TAB (Queue Mode):")
        print(str(e))
        print(f"==========================================")
        system_state["is_running"] = False

def check_and_download_completed_scenes_mobile(k, scenes, page, output_dir, session):
    cards = page.locator('#mVideoGrid .m-media-card')
    for j in range(k):
        scene = scenes[j]
        if scene.status != "Processing":
            continue
        try:
            card_idx = k - 1 - j
            if cards.count() <= card_idx:
                continue
            target_item = cards.nth(card_idx)
            
            err_locator = target_item.locator('.m-media-error, .lite-error-badge, .m-error')
            if err_locator.is_visible():
                print(f"[Mobile Queue] Scene {scene.id} bị lỗi render từ phía AI Studio!")
                scene.status = "Error"
                scene.error_msg = "Lỗi render từ AI Studio (Mobile)"
                session.commit()
                continue
                
            dl_btn = target_item.locator('button[data-action="download"]')
            video_thumb = target_item.locator('video.m-media-thumb, video')
            src_url = video_thumb.get_attribute('src') if video_thumb.is_visible() else None
            
            if dl_btn.is_visible() or (src_url and ".mp4" in src_url):
                print(f"[Mobile Queue] >>> Phát hiện Scene {scene.id} ĐÃ RENDER XONG! Đang tải về ngay...")
                vid_path = os.path.join(output_dir, f"scene_{scene.id}_{int(time.time())}.mp4")
                
                downloaded = False
                if src_url and src_url.startswith("http"):
                    try:
                        req = urllib.request.Request(src_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
                        with urllib.request.urlopen(req, timeout=30) as response, open(vid_path, 'wb') as out_file:
                            out_file.write(response.read())
                        downloaded = os.path.exists(vid_path) and os.path.getsize(vid_path) > 0
                    except Exception as ex:
                        print(f"[Mobile Queue] Lỗi tải HTTP trực tiếp: {ex}, chuyển sang expect_download...")
                        
                if not downloaded:
                    try:
                        with page.expect_download(timeout=30000) as download_info:
                            if src_url:
                                page.evaluate(f"""
                                    const a = document.createElement('a');
                                    a.href = '{src_url}';
                                    a.download = 'video_{scene.id}.mp4';
                                    document.body.appendChild(a);
                                    a.click();
                                    document.body.removeChild(a);
                                """)
                            else:
                                dl_btn.click()
                        download = download_info.value
                        download.save_as(vid_path)
                        downloaded = True
                    except Exception as ex:
                        print(f"[Mobile Queue] Lỗi expect_download cho Scene {scene.id}: {ex}")
                        
                if downloaded:
                    scene.video_path = vid_path
                    scene.status = "Completed"
                    session.commit()
                    print(f"[Mobile Queue] ===> ĐÃ XONG SCENE {scene.id} & LƯU TẠI {vid_path} (Cập nhật trạng thái Completed ngay lập tức!)")
        except Exception as e:
            print(f"[Mobile Queue] Lỗi kiểm tra Scene {scene.id}: {e}")

def run_single_tab_mobile(core_id, project_id, source_mode, ai_model, output_dir, session, page, batch_size=3):
    batch_num = 1
    print(f"[Core {core_id}] Đang truy cập trực tiếp https://ai.tool98.com/mobile ...")
    page.goto("https://ai.tool98.com/mobile", wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)
    
    while system_state["is_running"]:
        try:
            scenes = session.query(Scene).filter_by(project_id=project_id, status="Pending").order_by(Scene.order_index.asc()).limit(batch_size).all()
            if not scenes:
                print(f"[Core {core_id}] [Mobile Queue] Toàn bộ các cảnh của dự án {project_id} đã hoàn thành!")
                break
                
            print(f"==========================================================================")
            print(f"[Core {core_id}] BẮT ĐẦU ĐỢT {batch_num}: Chạy {len(scenes)} cảnh (Giới hạn {batch_size} cảnh/đợt theo cấu hình)...")
            print(f"==========================================================================")
            
            # 1. Bấm nút Tạo dự án (#mCreateProjectBtn)
            print(f"[Core {core_id}] Bấm nút Tạo Dự Án Mới (#mCreateProjectBtn) cho Đợt {batch_num}...")
            create_btn = page.locator('#mCreateProjectBtn')
            create_btn.wait_for(state="visible", timeout=20000)
            create_btn.click()
            time.sleep(1)
            
            # 2. Xóa tên cũ (mặc định là "Dự án mới") rồi viết lại tên dự án trong #mModalInput, bấm #mModalOk
            print(f"[Core {core_id}] Điền tên dự án trong modal Mobile...")
            modal_input = page.locator('#mModalInput')
            modal_input.wait_for(state="visible", timeout=10000)
            modal_input.fill("")
            time.sleep(0.3)
            modal_input.fill(f"Mobile_{project_id}_B{batch_num}_{int(time.time())}")
            time.sleep(0.5)
            page.locator('#mModalOk').click()
            
            # 3. Đợi 2s nó tự load đang ở trong dự án vừa tạo
            print(f"[Core {core_id}] Đang chờ vào trong dự án vừa tạo...")
            time.sleep(2)
            
            # GIAI ĐOẠN 1: Gửi lần lượt tối đa batch_size cảnh vào hàng đợi Mobile
            for i, scene in enumerate(scenes):
                if not system_state["is_running"]:
                    print(f"[Mobile Queue] Dừng gửi thêm cảnh theo yêu cầu từ người dùng.")
                    break
                    
                # Kiểm tra ngay nếu có video nào trước đó vừa render xong thì tải & cập nhật trạng thái Completed lập tức
                check_and_download_completed_scenes_mobile(i, scenes, page, output_dir, session)
                    
                print(f"[Mobile Queue] --- Đợt {batch_num} - Chuẩn bị cảnh {i+1}/{len(scenes)} (ID: {scene.id}) ---")
                scene.status = "Processing"
                session.commit()
                
                # 0. Chuyển về Tab "Reference" trước khi thao tác ảnh ref (đặc biệt quan trọng cho từ video thứ 2)
                print(f"[Mobile Queue] Chuyển về Tab 'Reference' để quản lý ảnh ref...")
                try:
                    page.locator('button.m-tab:not([data-tab="video"]), button.m-tab[data-tab="ref"], button.m-tab[data-tab="reference"]').first.click(timeout=2000)
                except:
                    pass
                time.sleep(1) # Delay 1s an toàn sau thao tác
                
                # A. Xóa ảnh ref cũ (nếu có) bằng cách ấn nút Xóa trên card Reference và xác nhận OK trong modal
                print(f"[Mobile Queue] Xóa ảnh ref cũ của cảnh trước (nếu có)...")
                while True:
                    ref_del_btn = page.locator('.m-media-card:has(.m-muted:text-is("Reference")) button[data-action="delete"], .m-media-card button[data-action="delete"]').first
                    if ref_del_btn.is_visible():
                        try:
                            ref_del_btn.click(timeout=3000)
                            time.sleep(1)
                            # Xác nhận trong modal Xóa (#mModalOk)
                            modal_ok = page.locator('#mModalOk')
                            if modal_ok.is_visible():
                                modal_ok.click(timeout=3000)
                                time.sleep(1)
                        except:
                            break
                    else:
                        break
                        
                # B. Tải ảnh ref lên (nếu có)
                image_path = scene.image_path if scene.image_path != "TEXT_ONLY" else None
                if image_path and os.path.exists(image_path):
                    print(f"[Mobile Queue] Uploading ref image: {image_path}")
                    for attempt in range(3):
                        try:
                            upload_btn = page.locator('#mUploadRefBtn')
                            upload_btn.click(timeout=5000)
                            time.sleep(1) # Delay 1s chờ modal "Chọn nơi lưu Ref" hiện ra
                            
                            ref_curr_btn = page.locator('button:has-text("Ref cảnh hiện tại")').first
                            if ref_curr_btn.is_visible():
                                print(f"[Mobile Queue] Chọn 'Ref cảnh hiện tại' trong modal...")
                                with page.expect_file_chooser(timeout=10000) as fc_info:
                                    ref_curr_btn.click()
                            else:
                                with page.expect_file_chooser(timeout=10000) as fc_info:
                                    upload_btn.click()
                            file_chooser = fc_info.value
                            file_chooser.set_files(image_path)
                            print(f"[Mobile Queue] Đã upload ảnh ref, đợi 8s cho ảnh tải xong và hiển thị trên UI...")
                            time.sleep(8) # Delay 8s cho ảnh ref tải hoàn tất và card render lên UI
                            break
                        except Exception as e:
                            print(f"[Mobile Queue] Upload attempt {attempt+1} failed: {e}")
                            time.sleep(2)
                            
                # C. Chọn card Reference đầu tiên bằng cách bấm vào đó
                print(f"[Mobile Queue] Bấm chọn Card Reference đầu tiên...")
                try:
                    ref_card = page.locator('.m-media-card:has(.m-muted:text-is("Reference")), .m-media-card').first
                    ref_card.wait_for(state="visible", timeout=30000)
                    ref_card.click(timeout=5000)
                    time.sleep(2) # Delay 2s sau bấm chọn card để nút hành động xuất hiện ổn định
                except Exception as e:
                    print(f"[Mobile Queue] Lỗi khi bấm chọn card ref: {e}")
                    
                # D. Bấm nút "Chọn nguồn" (data-action="select" hoặc "add-ref") và delay 3s
                print(f"[Mobile Queue] Bấm nút 'Chọn nguồn' và chờ 3s...")
                try:
                    select_src_btn = page.locator('.m-media-card button[data-action="select"], button:has-text("Chọn nguồn"), button[data-action="add-ref"]').first
                    select_src_btn.wait_for(state="visible", timeout=30000)
                    select_src_btn.click()
                    time.sleep(3) # Đặc biệt đoạn chọn ảnh ref cần delay đủ 3s cho ổn định
                except Exception as e:
                    print(f"[Mobile Queue] Lỗi khi bấm Chọn nguồn cho ảnh ref: {e}")
                    
                # E. Ấn vào tab "Tạo video" (data-tab="video")
                print(f"[Mobile Queue] Chuyển sang Tab 'Tạo video'...")
                try:
                    page.locator('button.m-tab[data-tab="video"], button:has-text("Tạo video")').first.click()
                except:
                    pass
                time.sleep(2) # Delay 2s sau khi sang tab Tạo video
                
                # F. Nhập prompt và thiết lập thông số video
                prompt_text = scene.prompt or ""
                for attempt in range(3):
                    try:
                        prompt_input = page.locator('#mPromptVideo')
                        prompt_input.wait_for(state="visible", timeout=5000)
                        prompt_input.click()
                        time.sleep(0.3)
                        prompt_input.fill(prompt_text)
                        break
                    except Exception as e:
                        print(f"[Mobile Queue] Thử điền prompt lần {attempt+1} gặp lỗi ({str(e)}), thử lại...")
                        time.sleep(1)
                time.sleep(1) # Delay 1s sau mỗi thao tác
                
                # Chỉ cấu hình các thông số (Nguồn, Độ phân giải, Thời lượng, Tỷ lệ) ở video đầu tiên (i == 0)
                if i == 0:
                    print(f"[Mobile Queue] Cấu hình thông số video lần đầu (Nguồn, Độ phân giải, Thời lượng, Tỷ lệ)...")
                    # Chọn Nguồn video (#mVideoSourceMode): "references" nếu có ref ảnh, ngược lại chọn "text" hoặc source_mode
                    try:
                        target_mode = 'references' if image_path else 'text'
                        page.locator('#mVideoSourceMode').select_option(target_mode)
                        time.sleep(1) # Delay 1s
                    except Exception:
                        pass
                        
                    # Chọn Độ phân giải (#mVideoResolution): "1080P"
                    try:
                        page.locator('#mVideoResolution').select_option("1080P")
                        time.sleep(1) # Delay 1s
                    except Exception:
                        pass
                        
                    # Chọn Thời lượng (#mVideoDuration): 8s hoặc theo duration của scene
                    try:
                        duration_val = getattr(scene, 'duration', 8) or 8
                        duration_val = max(3, min(12, int(duration_val)))
                        page.locator('#mVideoDuration').select_option(str(duration_val))
                        time.sleep(1) # Delay 1s
                    except Exception:
                        pass
                        
                    # Chọn Tỷ lệ (#mVideoAspect): "16:9"
                    try:
                        page.locator('#mVideoAspect').select_option("16:9")
                        time.sleep(1) # Delay 1s
                    except Exception:
                        pass
                else:
                    print(f"[Mobile Queue] Video thứ {i+1}: Giữ nguyên config từ trước, chỉ thay Prompt và Ref ảnh.")
                    
                # G. Bấm nút Tạo video (#mGenerateVideoBtn)
                print(f"[Mobile Queue] Bấm nút Tạo Video (#mGenerateVideoBtn) cho Scene {scene.id}...")
                page.locator('#mGenerateVideoBtn').click()
                time.sleep(2)
                
                # H. Chờ cảnh vào trạng thái tạo video (> 1% hoặc render xong)
                print(f"[Mobile Queue] Chờ Scene {scene.id} vào render (thoát trạng thái hàng đợi ban đầu)...")
                while system_state["is_running"]:
                    check_and_download_completed_scenes_mobile(i + 1, scenes, page, output_dir, session)
                    
                    cards = page.locator('.m-media-card:not(:has(.m-muted:text-is("Reference"))):not(:has-text("Reference"))')
                    if cards.count() >= i + 1:
                        first_item = cards.first
                        if first_item.locator('button[data-action="download"], video.m-media-thumb').is_visible():
                            print(f"[Mobile Queue] Scene {scene.id} đã hoàn tất render sớm!")
                            break
                        first_percent = first_item.locator('.m-placeholder-percent')
                        if first_percent.is_visible():
                            txt = first_percent.inner_text().strip()
                            if "%" in txt:
                                print(f"[Mobile Queue] Scene {scene.id} đã vào render ({txt}), tiếp tục cảnh tiếp theo...")
                                break
                    time.sleep(2)
                    
            # GIAI ĐOẠN 2: Giám sát liên tục và tải ngay lập tức bất kỳ video nào vừa render xong trong đợt này
            print(f"[Core {core_id}] Đã gửi đủ {len(scenes)} cảnh của Đợt {batch_num}. Bắt đầu giám sát và tải video render xong...")
            while system_state["is_running"]:
                pending_or_proc = [s for s in scenes if s.status == "Processing"]
                if not pending_or_proc:
                    print(f"[Core {core_id}] Tất cả {len(scenes)} cảnh (Đợt {batch_num}) đã được render và tải về hoàn tất!")
                    break
                    
                check_and_download_completed_scenes_mobile(len(scenes), scenes, page, output_dir, session)
                time.sleep(3)
                
            batch_num += 1
            print(f"[Core {core_id}] ---> Hoàn thành Đợt {batch_num-1}! Chuẩn bị sang Đợt {batch_num} nếu còn cảnh Pending...")
            time.sleep(2)
        except Exception as e:
            print(f"==========================================")
            print(f"[Core {core_id}] LỖI TỔNG CHẾ ĐỘ 1 TAB MOBILE (Đợt {batch_num}):")
            print(str(e))
            print(f"==========================================")
            time.sleep(3)
            break
    print(f"[Core {core_id}] Dừng hoàn toàn chế độ 1 Tab Mobile.")
    try:
        proc_scenes = session.query(Scene).filter_by(project_id=project_id, status="Processing").all()
        for s in proc_scenes:
            s.status = "Pending"
        session.commit()
    except Exception:
        pass

def worker_loop(core_id, project_id, target_scene_id=None, source_mode="start_end", ai_model="gen_01", execution_mode="default", batch_size=3):
    base_dir = get_runtime_path()
    master_user_data_dir = os.path.join(base_dir, "user_data")
    
    # Nhân bản profile (user_data) cho từng core để chạy song song nhiều luồng
    import shutil
    user_data_dir = os.path.join(base_dir, f"user_data_core_{core_id}")
    if os.path.exists(master_user_data_dir):
        try:
            if os.path.exists(user_data_dir):
                shutil.rmtree(user_data_dir, ignore_errors=True)
            shutil.copytree(master_user_data_dir, user_data_dir, dirs_exist_ok=True)
        except Exception as e:
            print(f"[Core {core_id}] Lỗi clone profile: {e}. Vẫn tiếp tục...")
    else:
        user_data_dir = master_user_data_dir
        
    output_dir = os.path.join(base_dir, "output", f"project_{project_id}")
    os.makedirs(output_dir, exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            channel="chrome",
            args=['--disable-blink-features=AutomationControlled', '--start-maximized', '--disable-features=IsolateOrigins,site-per-process'],
            no_viewport=True,
            accept_downloads=True
        )
        # Chặn Chrome hiện popup hỏi quyền truy cập folder cũ (File System Access API)
        browser.add_init_script("""
            const grant = async () => 'granted';
            if (window.FileSystemHandle && window.FileSystemHandle.prototype) {
                window.FileSystemHandle.prototype.queryPermission = grant;
                window.FileSystemHandle.prototype.requestPermission = grant;
            }
            if (window.FileSystemDirectoryHandle && window.FileSystemDirectoryHandle.prototype) {
                window.FileSystemDirectoryHandle.prototype.queryPermission = grant;
                window.FileSystemDirectoryHandle.prototype.requestPermission = grant;
            }
            if (window.FileSystemFileHandle && window.FileSystemFileHandle.prototype) {
                window.FileSystemFileHandle.prototype.queryPermission = grant;
                window.FileSystemFileHandle.prototype.requestPermission = grant;
            }
        """)
        page = browser.pages[0] if browser.pages else browser.new_page()
        
        session = SessionLocal()
        
        try:
            if execution_mode == "single_tab_queue" and not target_scene_id:
                run_single_tab_queue(core_id, project_id, source_mode, ai_model, output_dir, session, page)
                return
            if execution_mode == "single_tab_mobile" and not target_scene_id:
                run_single_tab_mobile(core_id, project_id, source_mode, ai_model, output_dir, session, page, batch_size=batch_size)
                return
                
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
                    page.wait_for_selector('.video-resolution-select', timeout=60000)
                    time.sleep(3)
                    
                    # 5. Set Parameters
                    page.locator('.video-resolution-select').select_option('1080P')
                    time.sleep(1)
                    try:
                        page.locator('.video-quality-select').select_option('low')
                        time.sleep(0.5)
                    except Exception:
                        pass
                    page.locator('.video-ratio-select').select_option('16:9')
                    time.sleep(1)
                    
                    # Duration input (need to clear first)
                    duration_val = getattr(scene, 'duration', 7) or 7
                    duration_val = max(1, min(13, int(duration_val)))
                    page.locator('.video-duration-input').fill(str(duration_val))
                    time.sleep(1)
                    
                    page.locator('.video-model-input').select_option(ai_model)
                    time.sleep(1)
                    page.locator('.video-source-mode-select').select_option(source_mode)
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
                    card_locator.wait_for(state="visible", timeout=600000) # 10 minutes max
                    
                    # Chờ cho video thực sự render xong (hiện ảnh bìa thumbnail có chứa link tải)
                    img_locator = card_locator.locator('.lite-video-thumb')
                    img_locator.wait_for(state="visible", timeout=600000) # Chờ thêm tối đa 10 phút nữa nếu cần
                    
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
