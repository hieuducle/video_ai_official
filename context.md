# Hướng dẫn Cài đặt & Chạy Dự án Tool Video AI (video_ai_official)

Dự án này là hệ thống tự động hóa sử dụng Playwright và FastAPI để điều khiển tạo video AI hàng loạt. Dưới đây là các bước để cài đặt và khởi chạy dự án từ đầu trên một máy tính mới.

## 1. Yêu cầu Hệ thống
- Hệ điều hành: Windows / macOS / Linux
- Python: Phiên bản 3.9 trở lên (đã thêm vào PATH)

## 2. Các bước Cài đặt

### Bước 2.1: Tải mã nguồn
Đảm bảo bạn đã sao chép hoặc tải toàn bộ mã nguồn vào một thư mục (ví dụ: `D:\workspace\mmo\video_ai_official`).

### Bước 2.2: Cài đặt thư viện Python
Mở Terminal (hoặc Command Prompt / PowerShell), di chuyển vào thư mục dự án và chạy lệnh cài đặt thư viện từ file `requirements.txt`:

```bash
cd D:\workspace\mmo\video_ai_official
pip install -r requirements.txt
```

### Bước 2.3: Cài đặt Trình duyệt cho Playwright
Dự án sử dụng Playwright để tự động hóa thao tác trên trình duyệt. Lần đầu tiên sử dụng (hoặc sau khi cài đặt thư viện trên môi trường mới), bạn bắt buộc phải tải lõi trình duyệt của Playwright bằng lệnh sau:

```bash
playwright install
```

*(Quá trình này có thể mất một chút thời gian tùy thuộc vào tốc độ mạng để tải Chromium, Firefox, WebKit).*

## 3. Cách khởi chạy Ứng dụng

Sau khi cài đặt xong mọi thứ, để bắt đầu chạy ứng dụng, bạn sử dụng lệnh:

```bash
python main.py
```

- **Truy cập Giao diện:** Khi chạy thành công, ứng dụng web (FastAPI) sẽ hoạt động tại địa chỉ: `http://127.0.0.1:8003`
- Bạn mở trình duyệt, truy cập vào đường link trên để sử dụng giao diện quản lý cấu hình và hàng đợi (Queue).

## 4. Ghi chú Thêm
- **Cơ sở dữ liệu:** Các trạng thái (Pending, Processing, Error, Completed...) được lưu trữ bằng SQLite (cấu hình trong `models.py`). File database sẽ tự động được tạo ra (thường là `db.sqlite3` hoặc lưu dưới dạng local theo code).
- **Thư mục User Data (Playwright):** Chương trình tự động tạo ra thư mục `user_data` hoặc `user_data_core_X` để lưu session/cookie (giúp không phải đăng nhập nhiều lần).
- **Video & Image Ref Output:** Khi video hoàn tất sẽ được tự động tải về theo logic thư mục cục bộ của hệ thống (bạn có thể kiểm tra tab tải về hoặc thư mục output đã chỉ định).

Chúc bạn thành công!
