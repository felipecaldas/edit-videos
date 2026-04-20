with open('/app/tests/test_comfyui_client.py', 'r') as f:
    content = f.read()

# Replace the test methods that call _output_filename_for_index
old_test1 = '''    def test_video_outputs_use_uuid_based_filenames(self):
        """Video outputs should always get UUID-based filenames to avoid collisions."""
        name1 = self.client._output_filename_for_index(
            media_type="video/mp4",
            provided="ComfyUI_00002_.mp4",
            index=0,
        )
        name2 = self.client._output_filename_for_index(
            media_type="video/mp4",
            provided="ComfyUI_00002_.mp4",
            index=0,
        )

        # Names should have the index prefix and .mp4 extension
        assert name1.startswith("000_")
        assert name1.endswith(".mp4")
        assert name2.startswith("000_")
        assert name2.endswith(".mp4")

        # Even with identical inputs, UUID portion should make them different
        assert name1 != name2'''

new_test1 = '''    def test_video_outputs_use_uuid_based_filenames(self):
        """Video outputs should always get UUID-based filenames to avoid collisions."""
        from videomerge.services.comfyui.utils import output_filename_for_index

        name1 = output_filename_for_index(
            media_type="video/mp4",
            provided="ComfyUI_00002_.mp4",
            index=0,
        )
        name2 = output_filename_for_index(
            media_type="video/mp4",
            provided="ComfyUI_00002_.mp4",
            index=0,
        )

        # Names should have the index prefix and .mp4 extension
        assert name1.startswith("000_")
        assert name1.endswith(".mp4")
        assert name2.startswith("000_")
        assert name2.endswith(".mp4")

        # Even with identical inputs, UUID portion should make them different
        assert name1 != name2'''

old_test2 = '''    def test_non_video_outputs_preserve_sanitized_name(self):
        """Non-video outputs (e.g. images) should preserve sanitized provided names."""
        name = self.client._output_filename_for_index(
            media_type="image/png",
            provided="my image.png",
            index=3,
        )

        # Index prefix and sanitized basename should both appear
        assert name.startswith("003_")
        assert name.endswith(".png")
        assert "my_image.png" in name'''

new_test2 = '''    def test_non_video_outputs_preserve_sanitized_name(self):
        """Non-video outputs (e.g. images) should preserve sanitized provided names."""
        from videomerge.services.comfyui.utils import output_filename_for_index

        name = output_filename_for_index(
            media_type="image/png",
            provided="my image.png",
            index=3,
        )

        # Index prefix and sanitized basename should both appear
        assert name.startswith("003_")
        assert name.endswith(".png")
        assert "my_image.png" in name'''

content = content.replace(old_test1, new_test1)
content = content.replace(old_test2, new_test2)

with open('/app/tests/test_comfyui_client.py', 'w') as f:
    f.write(content)
print('Done')
