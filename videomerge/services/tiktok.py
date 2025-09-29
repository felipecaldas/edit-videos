import os
import shutil
import json
import math
import httpx
from videomerge.utils.logging import get_logger
from videomerge.config import TIKTOK_VIDEOS_ARCHIVE_FOLDER

logger = get_logger(__name__)


class TikTokService:
    """
    A service to handle video uploads to TikTok.
    """
    TIKTOK_API_BASE_URL = "https://open.tiktokapis.com/v2"

    async def upload_video(self, tiktok_bearer_token: str, file_path: str, privacy_level: str):
        """
        Uploads a video to TikTok.

        Args:
            tiktok_bearer_token: The TikTok OAuth bearer token.
            file_path: The full path to the video file.
            privacy_level: The privacy level for the video on TikTok.
        """
        logger.info(f"Starting TikTok upload for file: {file_path}")

        try:
            # 1. Get video title from manifest.json
            directory = os.path.dirname(file_path)
            manifest_path = os.path.join(directory, "manifest.json")

            if not os.path.exists(manifest_path):
                logger.error(f"manifest.json not found at {manifest_path}")
                raise FileNotFoundError(f"manifest.json not found at {manifest_path}")

            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            title = manifest.get("caption")
            if not title:
                logger.error("'caption' not found in manifest.json")
                raise ValueError("'caption' not found in manifest.json")

            # 2. Get video size
            if not os.path.exists(file_path):
                logger.error(f"Video file not found at {file_path}")
                raise FileNotFoundError(f"Video file not found at {file_path}")

            video_size = os.path.getsize(file_path)
            
            # 2.1. Determine chunking strategy
            MIN_CHUNK_SIZE = 5 * 1024 * 1024  # 5MB
            if video_size <= MIN_CHUNK_SIZE:
                chunk_size = video_size
                total_chunk_count = 1
            else:
                chunk_size = MIN_CHUNK_SIZE
                total_chunk_count = math.ceil(video_size / chunk_size)

            # 3. Initialize video upload
            init_url = f"{self.TIKTOK_API_BASE_URL}/post/publish/video/init/"
            headers = {
                "Authorization": f"Bearer {tiktok_bearer_token}",
                "Content-Type": "application/json",
            }
            init_payload = {
                "post_info": {
                    "title": title,
                    "privacy_level": privacy_level,
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                    "video_cover_timestamp_ms": 1000,
                    "brand_content_toggle": False,
                    "brand_organic_toggle": False,
                    "is_aigc": True
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunk_count
                }
            }

            async with httpx.AsyncClient() as client:
                logger.info(f"Initializing TikTok upload to {init_url}")
                response = await client.post(init_url, headers=headers, json=init_payload, timeout=60)
                response.raise_for_status()
                upload_data = response.json()

                if upload_data.get("error", {}).get("code") != "ok":
                    logger.error(f"TikTok API error during init: {upload_data['error']}")
                    raise Exception(f"TikTok API error: {upload_data['error']['message']}")

                upload_url = upload_data.get("data", {}).get("upload_url")
                if not upload_url:
                    logger.error("Upload URL not found in TikTok API response.")
                    raise Exception("Upload URL not found in TikTok API response.")

                # 4. Upload video file
                with open(file_path, 'rb') as video_file:
                    if total_chunk_count == 1:
                        logger.info(f"Uploading video binary to {upload_url}")
                        video_binary = video_file.read()
                        content_range = f"bytes 0-{video_size - 1}/{video_size}"
                        upload_headers = {
                            "Content-Type": "video/mp4",
                            "Content-Range": content_range
                        }
                        upload_response = await client.put(upload_url, content=video_binary, headers=upload_headers, timeout=300)
                        upload_response.raise_for_status()
                    else:
                        logger.info(f"Starting chunked upload of {total_chunk_count} chunks.")
                        for i in range(total_chunk_count):
                            start_byte = i * chunk_size
                            end_byte = min(start_byte + chunk_size - 1, video_size - 1)
                            
                            video_file.seek(start_byte)
                            chunk = video_file.read(end_byte - start_byte + 1)
                            
                            content_range = f"bytes {start_byte}-{end_byte}/{video_size}"
                            upload_headers = {
                                "Content-Type": "video/mp4",
                                "Content-Range": content_range
                            }
                            
                            logger.info(f"Uploading chunk {i + 1}/{total_chunk_count} to {upload_url}")
                            upload_response = await client.put(upload_url, content=chunk, headers=upload_headers, timeout=300)
                            upload_response.raise_for_status()
                        logger.info("All chunks uploaded successfully.")

            logger.info("Successfully uploaded video to TikTok.")

            # 5. Archive the folder
            try:
                archive_base_dir = TIKTOK_VIDEOS_ARCHIVE_FOLDER
                os.makedirs(archive_base_dir, exist_ok=True)
                
                folder_to_move = directory
                destination_path = os.path.join(archive_base_dir, os.path.basename(folder_to_move))

                logger.info(f"Archiving folder {folder_to_move} to {destination_path}")
                shutil.move(folder_to_move, destination_path)
                logger.info(f"Successfully archived folder {folder_to_move}.")

            except Exception as e:
                logger.exception(f"Failed to archive folder {directory}. The upload was successful, but archival failed.")
                # Do not re-raise, as the primary task (upload) was successful.

            return {"status": "success", "message": "Video uploaded to TikTok and archived successfully."}

        except FileNotFoundError as e:
            logger.exception("File not found during TikTok upload process.")
            raise e
        except ValueError as e:
            logger.exception("Value error during TikTok upload process.")
            raise e
        except httpx.HTTPStatusError as e:
            logger.exception(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
            raise e
        except Exception as e:
            logger.exception("An unexpected error occurred during TikTok upload.")
            raise e
