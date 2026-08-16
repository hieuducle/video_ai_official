# import requests

# # ==========================
# # CONFIG
# # ==========================
# LICENSE_KEY = "LIC-RZ2T1-OYKX6-7ECPJ-7LLR3"

# IMAGE_PATH = r"D:\workspace\mmo\video_ai_official\163_C_nh_163.jpg"

# PROMPT = """Overview: Lighting the stove. Under the metal wing at night, he kneels and blows softly into a small fire started underneath the large aluminum cowling. Authentic 1990s Studio Ghibli anime frame. The camera slowly pushes in in a Medium Wide shot as orange light glows. [Audio: Soft blowing, sudden crackle and pop of dry wood catching fire. STRICTLY NO BACKGROUND MUSIC, NO GUITAR, NO PIANO. PURE ASMR ACTION SOUNDS ONLY.]"""

# # ==========================
# # Upload image to Catbox
# # ==========================

# print("Uploading image...")

# with open(IMAGE_PATH, "rb") as f:
#     upload = requests.post(
#         "https://catbox.moe/user/api.php",
#         data={
#             "reqtype": "fileupload"
#         },
#         files={
#             "fileToUpload": f
#         }
#     )

# image_url = upload.text.strip()

# print("Image URL:")
# print(image_url)

# # ==========================
# # Call Video API
# # ==========================

# payload = {
#     "prompt": PROMPT,
#     "source_mode": "references",
#     "reference_images": [
#         image_url
#     ],
#     "resolution": "1080P",
#     "aspect_ratio": "16:9",
#     "duration_seconds": 12,
#     "profile": "gen_01",
#     "workspace": "internal"
# }

# headers = {
#     "Authorization": f"Bearer {LICENSE_KEY}",
#     "Content-Type": "application/json"
# }

# print("\nSending request...")

# r = requests.post(
#     "https://ai.tool98.com/api/v1/internal/videos/generate",
#     headers=headers,
#     json=payload,
#     timeout=120
# )

# print("\nStatus Code:", r.status_code)
# print("\nResponse:")
# print(r.text)


import requests
import time

LICENSE_KEY = "LIC-RZ2T1-OYKX6-7ECPJ-7LLR3"

headers = {
    "Authorization": f"Bearer {LICENSE_KEY}",
    "Content-Type": "application/json"
}

job_id = "504b21d0-d4de-4219-a6b8-60580bd85601"

while True:

    r = requests.post(
        "https://ai.tool98.com/api/v1/internal/jobs/get",
        headers=headers,
        json={
            "job_id": job_id
        }
    )

    data = r.json()

    print(data)

    result = data["result"]

    if result["status"] == "completed":

        print("Completed!")

        download_url = result["results"][0]["download_url"]

        print(download_url)

        video = requests.get(download_url)

        with open("output.mp4", "wb") as f:
            f.write(video.content)

        print("Saved output.mp4")

        break

    elif result["status"] == "failed":

        print(result["error_message"])
        break

    time.sleep(3)