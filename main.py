from fastapi import FastAPI, Request, Form, BackgroundTasks
import asyncio
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import os
import glob
import re
import threading
import subprocess
import uuid
from typing import List
from models import SessionLocal, Scene, Project

# Import the new AnimAI worker
from animai_worker import worker_loop, system_state

import sys

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def get_runtime_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

base_path = get_base_path()
static_dir = os.path.join(base_path, "static")
templates_dir = os.path.join(base_path, "templates")

if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app = FastAPI()
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)


@app.on_event("startup")
async def startup_event():
    session = SessionLocal()
    try:
        stuck_scenes = session.query(Scene).filter_by(status="Processing").all()
        for scene in stuck_scenes:
            scene.status = "Error"
            scene.error_msg = "Tiến trình bị ngắt đột ngột khi đang chạy (tắt app). Vui lòng thử lại."
        session.commit()
    except Exception as e:
        print(f"Lỗi khi dọn dẹp DB lúc khởi động: {e}")
    finally:
        session.close()

    # Suppress noisy ConnectionResetError logs in Windows asyncio
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        default_handler = loop.get_exception_handler()
        def custom_exception_handler(loop, context):
            exc = context.get("exception")
            if isinstance(exc, ConnectionResetError) and getattr(exc, 'winerror', None) == 10054:
                return # Ignore WinError 10054
            if default_handler:
                default_handler(loop, context)
            else:
                loop.default_exception_handler(context)
        loop.set_exception_handler(custom_exception_handler)
    except Exception:
        pass

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={"request": request, "system_state": system_state, "is_trial": False}
    )

@app.get("/api/projects")
async def get_projects():
    session = SessionLocal()
    projects = session.query(Project).all()
    data = [{"id": p.id, "name": p.name, "created_at": p.created_at, "project_type": p.project_type} for p in projects]
    session.close()
    return {"projects": data}

@app.post("/api/projects")
async def create_project(name: str = Form(...), project_type: str = Form("image")):
    session = SessionLocal()
    existing = session.query(Project).filter_by(name=name).first()
    if existing:
        session.close()
        return {"success": False, "error": "Tên dự án đã tồn tại."}
    
    project = Project(name=name, project_type=project_type)
    session.add(project)
    session.commit()
    project_id = project.id
    session.close()
    return {"success": True, "project_id": project_id}

@app.post("/api/delete_project")
async def delete_project(project_id: int = Form(...)):
    session = SessionLocal()
    project = session.query(Project).filter_by(id=project_id).first()
    if not project:
        session.close()
        return {"success": False, "error": "Không tìm thấy dự án."}
    
    safe_project_name = "".join(c for c in project.name if c.isalnum() or c in (' ', '_', '-')).strip()
    
    session.delete(project)
    session.commit()
    session.close()
    
    import shutil
    base_dir = get_runtime_path()
    output_dir = os.path.join(base_dir, "output", safe_project_name)
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir, ignore_errors=True)
        
    return {"success": True}

@app.post("/api/scan")
async def scan_directory(folder_path: str = Form(...), project_id: int = Form(...)):
    if not os.path.isdir(folder_path):
        return JSONResponse({"success": False, "error": "Thư mục không tồn tại."})
    
    # Tìm các file ảnh (png, jpg, jpeg, webp)
    extensions = ('*.png', '*.jpg', '*.jpeg', '*.webp')
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(folder_path, ext)))
        
    def natural_sort_key(s):
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
    
    files.sort(key=natural_sort_key)
    
    session = SessionLocal()
    
    max_order = session.query(Scene).filter_by(project_id=project_id).order_by(Scene.order_index.desc()).first()
    current_order = (max_order.order_index + 1) if max_order else 0

    added = 0
    for file_path in files:
        existing = session.query(Scene).filter_by(image_path=file_path, project_id=project_id).first()
        if not existing:
            scene = Scene(image_path=file_path, project_id=project_id, order_index=current_order)
            session.add(scene)
            current_order += 1
            added += 1
    session.commit()
    session.close()
    
    return {"success": True, "added": added, "total_found": len(files)}

@app.post("/api/add_text_scenes")
async def add_text_scenes(project_id: int = Form(...), count: int = Form(...)):
    if count <= 0:
        return {"success": False, "error": "Số lượng cảnh phải lớn hơn 0"}
    
    session = SessionLocal()
    max_order = session.query(Scene).filter_by(project_id=project_id).order_by(Scene.order_index.desc()).first()
    current_order = (max_order.order_index + 1) if max_order else 0

    for _ in range(count):
        scene = Scene(image_path="TEXT_ONLY", project_id=project_id, order_index=current_order)
        session.add(scene)
        current_order += 1
        
    session.commit()
    session.close()
    
    return {"success": True, "added": count}

@app.post("/api/import_text_json")
async def import_text_json(project_id: int = Form(...), prompts_json: str = Form(...)):
    import json
    try:
        prompts = json.loads(prompts_json)
    except:
        return {"success": False, "error": "Định dạng JSON không hợp lệ."}
        
    session = SessionLocal()
    max_order = session.query(Scene).filter_by(project_id=project_id).order_by(Scene.order_index.desc()).first()
    current_order = (max_order.order_index + 1) if max_order else 0

    added = 0
    for item in prompts:
        if isinstance(item, dict):
            prompt_text = item.get("camera_instruction") or item.get("prompt") or item.get("text") or str(item)
            duration_val = int(item.get("duration_seconds") or item.get("duration") or 7)
            scene_type = item.get("type") or "ref"
        else:
            prompt_text = str(item)
            duration_val = 7
            scene_type = "ref"
        duration_val = max(1, min(13, duration_val))
        scene = Scene(image_path="TEXT_ONLY", project_id=project_id, order_index=current_order, prompt=prompt_text, duration=duration_val, scene_type=scene_type)
        session.add(scene)
        current_order += 1
        added += 1
        
    session.commit()
    session.close()
    return {"success": True, "added": added}

@app.post("/api/update_prompt")
async def update_prompt(scene_id: int = Form(...), prompt: str = Form(...), duration: int = Form(None), scene_type: str = Form(None)):
    session = SessionLocal()
    scene = session.query(Scene).filter_by(id=scene_id).first()
    if scene:
        scene.prompt = prompt
        if duration is not None:
            scene.duration = max(1, min(13, int(duration)))
        if scene_type is not None:
            scene.scene_type = scene_type
        session.commit()
        success = True
    else:
        success = False
    session.close()
    return {"success": success}

@app.post("/api/retry")
async def retry_scene(scene_id: int = Form(...)):
    session = SessionLocal()
    scene = session.query(Scene).filter_by(id=scene_id).first()
    if scene:
        scene.status = "Pending"
        scene.error_msg = None
        session.commit()
        success = True
    else:
        success = False
    session.close()
    return {"success": success}

@app.post("/api/start")
async def start_workers(background_tasks: BackgroundTasks, cores: int = Form(1), project_id: int = Form(...), source_mode: str = Form("start_end"), ai_model: str = Form("gen_01"), execution_mode: str = Form("default")):
    if system_state["is_running"]:
        return {"success": False, "error": "Hệ thống đang chạy."}
    
    session = SessionLocal()
    pending_count = session.query(Scene).filter(Scene.status.in_(["Pending", "Error", "Processing"]), Scene.project_id == project_id).count()
    
    if pending_count == 0:
        session.close()
        return {"success": False, "error": "Tất cả các cảnh đã hoàn thành, không có việc gì để chạy!"}
        
    error_or_proc_scenes = session.query(Scene).filter(Scene.status.in_(["Error", "Processing"]), Scene.project_id == project_id).all()
    for scene in error_or_proc_scenes:
        scene.status = "Pending"
        scene.error_msg = None
    session.commit()
    session.close()
    
    if execution_mode in ["single_tab_queue", "single_tab_mobile"]:
        batch_size = max(1, int(cores))
        cores = 1
    else:
        batch_size = 3
    system_state["is_running"] = True
    system_state["active_cores"] = cores
    
    for i in range(cores):
        t = threading.Thread(target=worker_loop, args=(i+1, project_id, None, source_mode, ai_model, execution_mode, batch_size), daemon=True)
        t.start()
        
    return {"success": True, "message": f"Đã khởi động {cores} luồng cho dự án (giới hạn đợt {batch_size} cảnh)."}

@app.post("/api/stop")
async def stop_workers():
    system_state["is_running"] = False
    try:
        session = SessionLocal()
        proc_scenes = session.query(Scene).filter(Scene.status == "Processing").all()
        for scene in proc_scenes:
            scene.status = "Pending"
        session.commit()
        session.close()
    except Exception as e:
        print(f"[Stop] Error resetting processing scenes: {e}")
    return {"success": True, "message": "Đã dừng hệ thống và chuyển trạng thái các cảnh về Pending."}

@app.post("/api/login_server")
async def api_login_server():
    def _run_login():
        from playwright.sync_api import sync_playwright
        base_dir = get_runtime_path()
        user_data_dir = os.path.join(base_dir, "user_data")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                    channel="chrome",
                    args=['--disable-blink-features=AutomationControlled', '--start-maximized', '--disable-features=IsolateOrigins,site-per-process'],
                    no_viewport=True
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
                page.goto("https://ai.tool98.com/")
                try:
                    page.wait_for_event("close", timeout=0)
                except:
                    pass
                try:
                    browser.close()
                except:
                    pass
        except Exception as e:
            print("Login error:", e)

    t = threading.Thread(target=_run_login, daemon=True)
    t.start()
    return {"success": True, "message": "Đã mở cổng kết nối máy chủ AnimAI. Vui lòng đăng nhập và chọn Workspace, sau đó ĐÓNG CỬA SỔ ĐÓ LẠI để hoàn tất quá trình lưu trữ."}

@app.get("/api/status")
async def get_status(project_id: int = 0):
    session = SessionLocal()
    if project_id > 0:
        scenes = session.query(Scene).filter_by(project_id=project_id).order_by(Scene.order_index.asc(), Scene.id.asc()).all()
    else:
        scenes = []
    data = []
    for s in scenes:
        data.append({
            "id": s.id,
            "image_path": s.image_path,
            "prompt": s.prompt,
            "duration": getattr(s, 'duration', 7) or 7,
            "status": s.status,
            "video_path": s.video_path,
            "error_msg": s.error_msg,
            "scene_type": getattr(s, 'scene_type', 'ref') or 'ref'
        })
    session.close()
    return {"scenes": data, "is_running": system_state["is_running"], "active_cores": system_state["active_cores"]}

@app.post("/api/delete_scene")
async def delete_scene(scene_id: int = Form(...)):
    session = SessionLocal()
    scene = session.query(Scene).filter_by(id=scene_id).first()
    if scene:
        if scene.video_path and os.path.exists(scene.video_path):
            try:
                os.remove(scene.video_path)
            except:
                pass
        session.delete(scene)
        session.commit()
        success = True
    else:
        success = False
    session.close()
    return {"success": success}

@app.post("/api/reorder")
async def reorder_scenes(scene_ids: str = Form(...)):
    ids = [int(x) for x in scene_ids.split(",") if x.strip()]
    session = SessionLocal()
    for index, sid in enumerate(ids):
        scene = session.query(Scene).filter_by(id=sid).first()
        if scene:
            scene.order_index = index
    session.commit()
    session.close()
    return {"success": True}

@app.post("/api/start_single")
async def start_single(background_tasks: BackgroundTasks, scene_id: int = Form(...), source_mode: str = Form("start_end"), ai_model: str = Form("gen_01"), execution_mode: str = Form("default")):
    session = SessionLocal()
    scene = session.query(Scene).filter_by(id=scene_id).first()
    if not scene:
        session.close()
        return {"success": False, "error": "Không tìm thấy cảnh."}
    
    scene.status = "Pending"
    scene.error_msg = None
    project_id = scene.project_id
    session.commit()
    session.close()
    
    unique_core_id = 999000 + scene_id
    t = threading.Thread(target=worker_loop, args=(unique_core_id, project_id, scene_id, source_mode, ai_model, execution_mode), daemon=True)
    t.start()
    return {"success": True, "message": "Đã bắt đầu tạo video cho cảnh này."}

def get_video_duration(file_path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return float(res.stdout.strip())
    except Exception:
        return 0.0

@app.post("/api/merge")
async def merge_videos(project_id: int = Form(...), transition: str = Form("none")):
    session = SessionLocal()
    project = session.query(Project).filter_by(id=project_id).first()
    safe_project_name = "".join(c for c in project.name if c.isalnum() or c in (' ', '_', '-')).strip() if project else f"project_{project_id}"
    scenes = session.query(Scene).filter_by(project_id=project_id, status="Completed").order_by(Scene.order_index.asc()).all()
    session.close()
    
    valid_scenes = [s for s in scenes if s.video_path and os.path.exists(s.video_path)]
    if len(valid_scenes) < 2:
        return {"success": False, "error": "Cần ít nhất 2 video đã hoàn thành để gộp."}
        
    base_dir = get_runtime_path()
    output_dir = os.path.join(base_dir, "output", safe_project_name)
    os.makedirs(output_dir, exist_ok=True)
    
    list_path = os.path.join(output_dir, f"list_{project_id}_{uuid.uuid4().hex[:6]}.txt")
    final_output = os.path.join(output_dir, f"Full_Movie_{safe_project_name}_{uuid.uuid4().hex[:6]}.mp4")
    
    cmd = []
    
    if transition == "none":
        with open(list_path, 'w', encoding='utf-8') as f:
            for s in valid_scenes:
                safe_path = s.video_path.replace('\\', '/')
                f.write(f"file '{safe_path}'\n")
                    
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", 
            "-i", list_path, "-c", "copy", final_output
        ]
    else:
        inputs = []
        filter_complex = ""
        offset = 0.0
        duration = 0.3
        
        durations = []
        for s in valid_scenes:
            inputs.extend(["-i", s.video_path])
            durations.append(get_video_duration(s.video_path))
            
        last_out = "0:v"
        for i in range(1, len(valid_scenes)):
            offset += durations[i-1] - duration
            out_name = f"v{i}"
            in_name = f"{i}:v"
            filter_complex += f"[{last_out}][{in_name}]xfade=transition={transition}:duration={duration}:offset={offset:.2f}[{out_name}];"
            last_out = out_name
            
        filter_complex = filter_complex.rstrip(";")
        cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", filter_complex, "-map", f"[{last_out}]", "-c:v", "libx264", "-crf", "17", "-preset", "slow", "-pix_fmt", "yuv420p", "-an", final_output]
    
    try:
        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if process.returncode != 0:
            return {"success": False, "error": f"Lỗi FFmpeg: {process.stderr}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)
            
    return {"success": True, "merged_video": final_output}

@app.get("/api/check_merged")
async def check_merged(project_id: int):
    session = SessionLocal()
    project = session.query(Project).filter_by(id=project_id).first()
    if not project:
        session.close()
        return {"exists": False}
    
    safe_project_name = "".join(c for c in project.name if c.isalnum() or c in (' ', '_', '-')).strip()
    session.close()
    
    base_dir = get_runtime_path()
    output_dir = os.path.join(base_dir, "output", safe_project_name)
    
    if not os.path.exists(output_dir):
        return {"exists": False}
        
    merged_files = glob.glob(os.path.join(output_dir, "Full_Movie_*.mp4"))
    if not merged_files:
        return {"exists": False}
        
    latest_file = max(merged_files, key=os.path.getmtime)
    return {"exists": True, "path": latest_file}

from fastapi.responses import FileResponse
@app.get("/api/image")
async def get_image(path: str):
    if os.path.exists(path):
        return FileResponse(path)
    return HTMLResponse("Image not found", status_code=404)

@app.get("/api/video")
async def get_video(path: str):
    video_files = glob.glob(path) if path else []
    if video_files:
        return FileResponse(video_files[0], media_type="video/mp4")
    return JSONResponse(status_code=404, content={"error": "File not found"})

if __name__ == "__main__":
    import uvicorn
    import multiprocessing
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8003)
