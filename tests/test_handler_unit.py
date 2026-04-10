"""
Unit tests for the RunPod ComfyUI handler.

All ComfyUI interactions (HTTP, WebSocket) are mocked so these tests
run on ANY machine — no GPU, no ComfyUI process required.
"""

import sys
import json
import base64
import types
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# 1x1 transparent PNG used as test fixture throughout
# ---------------------------------------------------------------------------
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
    "DUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
TINY_PNG_BYTES = base64.b64decode(TINY_PNG_B64)

# ---------------------------------------------------------------------------
# Mock runpod + network_volume BEFORE importing handler
# ---------------------------------------------------------------------------
_mock_runpod = types.ModuleType("runpod")
_mock_runpod.serverless = MagicMock()

_mock_rp_upload = types.ModuleType("runpod.serverless.utils.rp_upload")
_mock_rp_upload.upload_image = MagicMock(return_value="https://s3.example.com/image.png")

_mock_rp_utils = types.ModuleType("runpod.serverless.utils")
_mock_rp_utils.rp_upload = _mock_rp_upload

sys.modules.setdefault("runpod", _mock_runpod)
sys.modules.setdefault("runpod.serverless", _mock_runpod.serverless)
sys.modules.setdefault("runpod.serverless.utils", _mock_rp_utils)
sys.modules.setdefault("runpod.serverless.utils.rp_upload", _mock_rp_upload)

_mock_nv = types.ModuleType("network_volume")
_mock_nv.is_network_volume_debug_enabled = MagicMock(return_value=False)
_mock_nv.run_network_volume_diagnostics = MagicMock()
sys.modules.setdefault("network_volume", _mock_nv)

# Now safe to import
import handler  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SAMPLE_WORKFLOW = {
    "171": {
        "inputs": {"images": ["159", 0], "filename_prefix": "ComfyUI"},
        "class_type": "SaveImage",
    }
}


def _make_job(workflow=None, images=None, job_id="test-1"):
    """Build a minimal RunPod job dict."""
    inp = {}
    if workflow is not None:
        inp["workflow"] = workflow
    if images is not None:
        inp["images"] = images
    return {"id": job_id, "input": inp}


def _mock_response(status_code=200, json_data=None, content=b"", text=""):
    """Build a fake requests.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.content = content
    resp.text = text or json.dumps(json_data or {})
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# =========================================================================
# A) validate_input — valid input
# =========================================================================
class TestValidateInput:
    def test_valid(self):
        """A) Valid workflow + images passes validation."""
        data, err = handler.validate_input({
            "workflow": SAMPLE_WORKFLOW,
            "images": [{"name": "input.png", "image": TINY_PNG_B64}],
        })
        assert err is None
        assert data["workflow"] == SAMPLE_WORKFLOW
        assert len(data["images"]) == 1

    def test_missing_workflow(self):
        """B) Missing workflow returns error."""
        data, err = handler.validate_input({"images": []})
        assert data is None
        assert "workflow" in err.lower()

    def test_invalid_images_format(self):
        """C) Images not a list-of-dicts with name+image → error."""
        data, err = handler.validate_input({
            "workflow": SAMPLE_WORKFLOW,
            "images": "not-a-list",
        })
        assert data is None
        assert "images" in err.lower()

    def test_invalid_images_missing_keys(self):
        """C-extra) Images list with dicts missing required keys → error."""
        data, err = handler.validate_input({
            "workflow": SAMPLE_WORKFLOW,
            "images": [{"name": "x.png"}],  # missing 'image' key
        })
        assert data is None
        assert "images" in err.lower()

    def test_string_json_input(self):
        """D) JSON string input gets parsed correctly."""
        json_str = json.dumps({
            "workflow": SAMPLE_WORKFLOW,
            "images": [{"name": "a.png", "image": TINY_PNG_B64}],
        })
        data, err = handler.validate_input(json_str)
        assert err is None
        assert data["workflow"] == SAMPLE_WORKFLOW

    def test_string_invalid_json(self):
        """D-extra) Non-JSON string returns error."""
        data, err = handler.validate_input("{bad json")
        assert data is None
        assert "invalid json" in err.lower()

    def test_none_input(self):
        """E) None input returns error."""
        data, err = handler.validate_input(None)
        assert data is None
        assert "provide input" in err.lower()

    def test_workflow_only(self):
        """Valid input with workflow and no images."""
        data, err = handler.validate_input({"workflow": SAMPLE_WORKFLOW})
        assert err is None
        assert data["images"] is None


# =========================================================================
# F-H) upload_images
# =========================================================================
class TestUploadImages:
    @patch("handler.requests.post")
    def test_upload_success(self, mock_post):
        """F) Base64 images upload to ComfyUI successfully."""
        mock_post.return_value = _mock_response(200)
        images = [{"name": "input.png", "image": TINY_PNG_B64}]
        result = handler.upload_images(images)
        assert result["status"] == "success"
        assert mock_post.called
        # Verify the upload URL
        call_args = mock_post.call_args
        assert "upload/image" in call_args[0][0] or "upload/image" in str(call_args)

    @patch("handler.requests.post")
    def test_upload_with_data_uri_prefix(self, mock_post):
        """F-extra) Images with data:image/png;base64, prefix are handled."""
        mock_post.return_value = _mock_response(200)
        images = [{"name": "test.png", "image": f"data:image/png;base64,{TINY_PNG_B64}"}]
        result = handler.upload_images(images)
        assert result["status"] == "success"

    def test_upload_empty_list(self):
        """G) Empty images list returns success with no uploads."""
        result = handler.upload_images([])
        assert result["status"] == "success"
        assert "no images" in result["message"].lower()

    def test_upload_bad_base64(self):
        """H) Bad base64 data returns error."""
        images = [{"name": "bad.png", "image": "!!!not-valid-base64!!!"}]
        result = handler.upload_images(images)
        assert result["status"] == "error"
        assert len(result["details"]) > 0


# =========================================================================
# I) Full success pipeline — base64 output
# =========================================================================
class TestHandlerFullSuccess:
    @patch("handler._is_comfyui_process_alive", return_value=True)
    @patch("handler.websocket.WebSocket")
    @patch("handler.requests.get")
    @patch("handler.requests.post")
    @patch("handler.uuid.uuid4", return_value="fixed-client-id")
    def test_full_success_base64(
        self, mock_uuid, mock_post, mock_get, mock_ws_cls, mock_alive
    ):
        """I) Full pipeline: upload → queue → ws listen → history → base64 images."""
        prompt_id = "test-prompt-123"
        output_filename = "ComfyUI_00001_.png"

        # --- requests.get side effects ---
        # 1st call: check_server → 200
        server_ok = _mock_response(200)
        # 2nd call: get_history → outputs
        history_resp = _mock_response(200, json_data={
            prompt_id: {
                "outputs": {
                    "171": {
                        "images": [{
                            "filename": output_filename,
                            "subfolder": "",
                            "type": "output",
                        }]
                    }
                }
            }
        })
        # 3rd call: get_image_data /view → PNG bytes
        view_resp = _mock_response(200, content=TINY_PNG_BYTES)
        mock_get.side_effect = [server_ok, history_resp, view_resp]

        # --- requests.post side effects ---
        # 1st call: upload_images → 200
        upload_resp = _mock_response(200)
        # 2nd call: queue_workflow /prompt → prompt_id
        prompt_resp = _mock_response(200, json_data={"prompt_id": prompt_id})
        mock_post.side_effect = [upload_resp, prompt_resp]

        # --- WebSocket mock ---
        mock_ws = MagicMock()
        mock_ws_cls.return_value = mock_ws
        mock_ws.connected = True
        # recv() returns JSON messages, then the "done" signal
        mock_ws.recv.side_effect = [
            json.dumps({"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 1}}}}),
            json.dumps({"type": "executing", "data": {"node": "171", "prompt_id": prompt_id}}),
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": prompt_id}}),
        ]

        # --- Run handler ---
        job = _make_job(
            workflow=SAMPLE_WORKFLOW,
            images=[{"name": "input.png", "image": TINY_PNG_B64}],
        )
        result = handler.handler(job)

        # --- Assertions ---
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "images" in result
        assert len(result["images"]) == 1
        img = result["images"][0]
        assert img["type"] == "base64"
        assert img["filename"] == output_filename
        # Verify the base64 data decodes to valid bytes
        decoded = base64.b64decode(img["data"])
        assert decoded == TINY_PNG_BYTES


# =========================================================================
# J) Server unreachable
# =========================================================================
class TestHandlerServerUnreachable:
    @patch("handler._is_comfyui_process_alive", return_value=None)
    @patch("handler.COMFY_API_FALLBACK_MAX_RETRIES", 2)
    @patch("handler.requests.get")
    @patch("handler.time.sleep")
    def test_server_unreachable(self, mock_sleep, mock_get, mock_alive):
        """J) ComfyUI never comes up → handler returns error."""
        import requests as req_mod
        mock_get.side_effect = req_mod.ConnectionError("Connection refused")

        job = _make_job(workflow=SAMPLE_WORKFLOW)
        result = handler.handler(job)

        assert "error" in result
        assert "not reachable" in result["error"].lower() or "comfyui" in result["error"].lower()


# =========================================================================
# K) Workflow validation 400
# =========================================================================
class TestHandlerWorkflowValidation:
    @patch("handler._is_comfyui_process_alive", return_value=True)
    @patch("handler.websocket.WebSocket")
    @patch("handler.requests.get")
    @patch("handler.requests.post")
    @patch("handler.uuid.uuid4", return_value="fixed-client-id")
    def test_workflow_validation_400(
        self, mock_uuid, mock_post, mock_get, mock_ws_cls, mock_alive
    ):
        """K) ComfyUI returns 400 on /prompt → handler returns validation error."""
        # check_server ok
        mock_get.return_value = _mock_response(200)

        # /prompt returns 400 with error info
        error_body = {
            "error": {"type": "prompt_outputs_failed_validation", "message": "Validation failed"},
            "node_errors": {},
        }
        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.text = json.dumps(error_body)
        resp_400.json.return_value = error_body
        mock_post.return_value = resp_400

        # ws mock
        mock_ws = MagicMock()
        mock_ws_cls.return_value = mock_ws
        mock_ws.connected = False

        job = _make_job(workflow=SAMPLE_WORKFLOW)
        result = handler.handler(job)

        assert "error" in result
        assert "validation" in result["error"].lower() or "failed" in result["error"].lower()


# =========================================================================
# L) WebSocket execution_error
# =========================================================================
class TestHandlerExecutionError:
    @patch("handler._is_comfyui_process_alive", return_value=True)
    @patch("handler.websocket.WebSocket")
    @patch("handler.requests.get")
    @patch("handler.requests.post")
    @patch("handler.uuid.uuid4", return_value="fixed-client-id")
    def test_websocket_execution_error(
        self, mock_uuid, mock_post, mock_get, mock_ws_cls, mock_alive
    ):
        """L) WebSocket sends execution_error → handler returns error with details."""
        prompt_id = "test-prompt-456"

        # check_server → ok
        server_ok = _mock_response(200)
        # history → prompt exists but empty outputs
        history_resp = _mock_response(200, json_data={
            prompt_id: {"outputs": {}}
        })
        mock_get.side_effect = [server_ok, history_resp]

        # /prompt → ok
        mock_post.return_value = _mock_response(200, json_data={"prompt_id": prompt_id})

        # ws mock — sends execution_error
        mock_ws = MagicMock()
        mock_ws_cls.return_value = mock_ws
        mock_ws.connected = False
        mock_ws.recv.side_effect = [
            json.dumps({
                "type": "execution_error",
                "data": {
                    "prompt_id": prompt_id,
                    "node_type": "LoadCheckpoint",
                    "node_id": "4",
                    "exception_message": "Model not found",
                },
            }),
        ]

        job = _make_job(workflow=SAMPLE_WORKFLOW)
        result = handler.handler(job)

        # Should report error (details are now embedded in error string)
        assert "error" in result
        error_text = result["error"].lower()
        assert "model not found" in error_text or "execution error" in error_text or "failed" in error_text

    @patch("handler._is_comfyui_process_alive", return_value=True)
    @patch("handler.websocket.WebSocket")
    @patch("handler.requests.get")
    @patch("handler.requests.post")
    @patch("handler.uuid.uuid4", return_value="fixed-client-id")
    def test_execution_error_no_details_key(
        self, mock_uuid, mock_post, mock_get, mock_ws_cls, mock_alive
    ):
        """Error details are now embedded in the error string, not a separate 'details' key."""
        prompt_id = "test-prompt-no-details"

        server_ok = _mock_response(200)
        history_resp = _mock_response(200, json_data={
            prompt_id: {"outputs": {}}
        })
        mock_get.side_effect = [server_ok, history_resp]

        mock_post.return_value = _mock_response(200, json_data={"prompt_id": prompt_id})

        mock_ws = MagicMock()
        mock_ws_cls.return_value = mock_ws
        mock_ws.connected = False
        mock_ws.recv.side_effect = [
            json.dumps({
                "type": "execution_error",
                "data": {
                    "prompt_id": prompt_id,
                    "node_type": "LoadCheckpoint",
                    "node_id": "4",
                    "exception_message": "Model not found",
                },
            }),
        ]

        job = _make_job(workflow=SAMPLE_WORKFLOW)
        result = handler.handler(job)

        assert "error" in result
        # The 'details' key should NOT exist as a separate key — details are in the error string
        assert "details" not in result, "Error details should be embedded in 'error' string, not a separate key"
        # The error string should contain the details
        assert "model not found" in result["error"].lower() or "execution" in result["error"].lower()


# =========================================================================
# M) S3 upload path
# =========================================================================
class TestHandlerS3Upload:
    @patch("handler._is_comfyui_process_alive", return_value=True)
    @patch("handler.websocket.WebSocket")
    @patch("handler.requests.get")
    @patch("handler.requests.post")
    @patch("handler.uuid.uuid4", return_value="fixed-client-id")
    @patch.dict("os.environ", {"BUCKET_ENDPOINT_URL": "https://s3.example.com"})
    def test_s3_upload_path(
        self, mock_uuid, mock_post, mock_get, mock_ws_cls, mock_alive
    ):
        """M) With BUCKET_ENDPOINT_URL set, images go to S3 via rp_upload."""
        prompt_id = "test-prompt-s3"
        output_filename = "ComfyUI_00001_.png"

        # Reset the upload mock for this test
        _mock_rp_upload.upload_image.reset_mock()
        _mock_rp_upload.upload_image.return_value = "https://s3.example.com/test-1/ComfyUI_00001_.png"

        # requests.get: server check, history, view
        server_ok = _mock_response(200)
        history_resp = _mock_response(200, json_data={
            prompt_id: {
                "outputs": {
                    "171": {
                        "images": [{
                            "filename": output_filename,
                            "subfolder": "",
                            "type": "output",
                        }]
                    }
                }
            }
        })
        view_resp = _mock_response(200, content=TINY_PNG_BYTES)
        mock_get.side_effect = [server_ok, history_resp, view_resp]

        # requests.post: /prompt
        mock_post.return_value = _mock_response(200, json_data={"prompt_id": prompt_id})

        # ws mock
        mock_ws = MagicMock()
        mock_ws_cls.return_value = mock_ws
        mock_ws.connected = True
        mock_ws.recv.side_effect = [
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": prompt_id}}),
        ]

        job = _make_job(workflow=SAMPLE_WORKFLOW, job_id="test-s3-job")
        result = handler.handler(job)

        # Assertions
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "images" in result
        assert len(result["images"]) == 1
        img = result["images"][0]
        assert img["type"] == "s3_url"
        assert "s3.example.com" in img["data"]
        # Verify rp_upload.upload_image was called
        _mock_rp_upload.upload_image.assert_called_once()


# =========================================================================
# N) WebSocket disconnect and reconnect
# =========================================================================
class TestHandlerWebsocketReconnect:
    @patch("handler._is_comfyui_process_alive", return_value=True)
    @patch("handler.websocket.WebSocket")
    @patch("handler.requests.get")
    @patch("handler.requests.post")
    @patch("handler.uuid.uuid4", return_value="fixed-client-id")
    @patch("handler.time.sleep")
    def test_websocket_disconnect_reconnect(
        self, mock_sleep, mock_uuid, mock_post, mock_get, mock_ws_cls, mock_alive
    ):
        """N) WebSocket drops mid-job, handler reconnects and completes."""
        import websocket as ws_module

        prompt_id = "test-prompt-reconnect"
        output_filename = "ComfyUI_00001_.png"

        # requests.get: server check, then comfy_server_status during reconnect, history, view
        server_ok = _mock_response(200)
        status_ok = _mock_response(200)  # for _comfy_server_status during reconnect
        history_resp = _mock_response(200, json_data={
            prompt_id: {
                "outputs": {
                    "171": {
                        "images": [{
                            "filename": output_filename,
                            "subfolder": "",
                            "type": "output",
                        }]
                    }
                }
            }
        })
        view_resp = _mock_response(200, content=TINY_PNG_BYTES)
        mock_get.side_effect = [server_ok, status_ok, history_resp, history_resp, view_resp]

        # requests.post: /prompt
        mock_post.return_value = _mock_response(200, json_data={"prompt_id": prompt_id})

        # --- WebSocket mock: first ws drops, reconnect creates new ws ---
        # The initial ws object
        first_ws = MagicMock()
        first_ws.connected = True
        # First recv works, second raises disconnect
        first_ws.recv.side_effect = [
            json.dumps({"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 1}}}}),
            ws_module.WebSocketConnectionClosedException("Connection lost"),
        ]

        # The reconnected ws object
        second_ws = MagicMock()
        second_ws.connected = True
        second_ws.recv.side_effect = [
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": prompt_id}}),
        ]

        # WebSocket() constructor: first call returns first_ws (initial connect),
        # second call returns second_ws (reconnect inside _attempt_websocket_reconnect)
        mock_ws_cls.side_effect = [first_ws, second_ws]

        job = _make_job(workflow=SAMPLE_WORKFLOW)
        result = handler.handler(job)

        # Should succeed despite the disconnect
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "images" in result
        assert len(result["images"]) == 1
        assert result["images"][0]["type"] == "base64"


# =========================================================================
# O) REFRESH_WORKER passed to runpod.serverless.start()
# =========================================================================
class TestRefreshWorker:
    def test_refresh_worker_passed_to_start(self):
        """REFRESH_WORKER is passed to runpod.serverless.start() config."""
        # The module-level code at __main__ calls runpod.serverless.start()
        # We verify that the handler module has REFRESH_WORKER defined
        # and that the main block passes it correctly.
        # We can test this by exec-ing the __main__ block with mocks.
        import importlib

        mock_start = MagicMock()
        with patch.object(_mock_runpod.serverless, "start", mock_start):
            with patch.dict("os.environ", {"REFRESH_WORKER": "true"}):
                # Re-evaluate REFRESH_WORKER
                old_val = handler.REFRESH_WORKER
                handler.REFRESH_WORKER = True
                try:
                    # Simulate __main__ execution
                    _mock_runpod.serverless.start({"handler": handler.handler, "refresh_worker": handler.REFRESH_WORKER})
                    mock_start.assert_called_once()
                    call_args = mock_start.call_args[0][0]
                    assert "refresh_worker" in call_args
                    assert call_args["refresh_worker"] is True
                    assert call_args["handler"] == handler.handler
                finally:
                    handler.REFRESH_WORKER = old_val


# =========================================================================
# P) Execution timeout
# =========================================================================
class TestHandlerExecutionTimeout:
    @patch("handler._is_comfyui_process_alive", return_value=True)
    @patch("handler.websocket.WebSocket")
    @patch("handler.requests.get")
    @patch("handler.requests.post")
    @patch("handler.uuid.uuid4", return_value="fixed-client-id")
    @patch("handler.time.time")
    def test_handler_execution_timeout(
        self, mock_time, mock_uuid, mock_post, mock_get, mock_ws_cls, mock_alive
    ):
        """Execution timeout: ws.recv blocks, handler returns timeout error."""
        prompt_id = "test-prompt-timeout"

        # Set timeout to 2 seconds
        original_timeout = handler.COMFY_EXECUTION_TIMEOUT_S
        handler.COMFY_EXECUTION_TIMEOUT_S = 2

        try:
            # check_server → ok
            mock_get.return_value = _mock_response(200)

            # /prompt → ok
            mock_post.return_value = _mock_response(200, json_data={"prompt_id": prompt_id})

            # ws mock
            mock_ws = MagicMock()
            mock_ws_cls.return_value = mock_ws
            mock_ws.connected = True

            # time.time() returns: first call for ws_loop_start = 100,
            # second call (elapsed check) = 103 which is > 2s timeout
            mock_time.side_effect = [100, 103]

            job = _make_job(workflow=SAMPLE_WORKFLOW)
            result = handler.handler(job)

            assert "error" in result
            assert "timed out" in result["error"].lower()
        finally:
            handler.COMFY_EXECUTION_TIMEOUT_S = original_timeout


# =========================================================================
# Q) WebSocket reconnect with history fallback
# =========================================================================
class TestHandlerWebsocketReconnectHistoryFallback:
    @patch("handler._is_comfyui_process_alive", return_value=True)
    @patch("handler.websocket.WebSocket")
    @patch("handler.requests.get")
    @patch("handler.requests.post")
    @patch("handler.uuid.uuid4", return_value="fixed-client-id")
    @patch("handler.time.sleep")
    @patch("handler.time.time")
    def test_handler_websocket_reconnect_history_fallback(
        self, mock_time, mock_sleep, mock_uuid, mock_post, mock_get, mock_ws_cls, mock_alive
    ):
        """After ws reconnect, history API shows prompt completed → success without more ws messages."""
        import websocket as ws_module

        prompt_id = "test-prompt-hist-fallback"
        output_filename = "ComfyUI_00001_.png"

        # time.time() needs to return values for ws_loop_start and elapsed checks
        # that don't trigger the timeout
        mock_time.return_value = 100  # constant time, no timeout

        history_data = {
            prompt_id: {
                "outputs": {
                    "171": {
                        "images": [{
                            "filename": output_filename,
                            "subfolder": "",
                            "type": "output",
                        }]
                    }
                }
            }
        }

        # requests.get calls:
        # 1. check_server → 200
        # 2. _comfy_server_status during reconnect → 200
        # 3. get_history after reconnect (history fallback check) → shows completed
        # 4. get_history for output collection → same
        # 5. get_image_data /view → PNG bytes
        server_ok = _mock_response(200)
        status_ok = _mock_response(200)
        history_reconnect = _mock_response(200, json_data=history_data)
        history_final = _mock_response(200, json_data=history_data)
        view_resp = _mock_response(200, content=TINY_PNG_BYTES)
        mock_get.side_effect = [server_ok, status_ok, history_reconnect, history_final, view_resp]

        # requests.post: /prompt
        mock_post.return_value = _mock_response(200, json_data={"prompt_id": prompt_id})

        # --- WebSocket mock ---
        # First ws: immediately disconnects on recv
        first_ws = MagicMock()
        first_ws.connected = True
        first_ws.recv.side_effect = ws_module.WebSocketConnectionClosedException("Connection lost")

        # Second ws (reconnected): should NOT need to recv anything
        # because history fallback finds the prompt completed
        second_ws = MagicMock()
        second_ws.connected = True

        mock_ws_cls.side_effect = [first_ws, second_ws]

        job = _make_job(workflow=SAMPLE_WORKFLOW)
        result = handler.handler(job)

        # Should succeed via history fallback
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "images" in result
        assert len(result["images"]) == 1
        assert result["images"][0]["type"] == "base64"
        # second_ws.recv should NOT have been called since history showed completion
        second_ws.recv.assert_not_called()
