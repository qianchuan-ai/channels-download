"""离线单元测试：不联网、不依赖 ffmpeg，全部用 mock 数据。

    python -m unittest discover -s tests -v   （在 skill 根目录执行）
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

from sphlib import auth, resolve  # noqa: E402


class TestParseShareId(unittest.TestCase):
    def test_share_text_with_link(self):
        text = "8-ZZI=http://x.cn 随便一段文案 https://weixin.qq.com/sph/AbC_d-12 快来看"
        self.assertEqual(resolve.parse_share_id(text), "AbC_d-12")

    def test_bare_short_link(self):
        self.assertEqual(resolve.parse_share_id("https://weixin.qq.com/sph/x9Yz01"), "x9Yz01")

    def test_preview_page_link(self):
        url = "https://channels.weixin.qq.com/finder-preview/pages/sph?id=PRE123&foo=bar"
        self.assertEqual(resolve.parse_share_id(url), "PRE123")

    def test_generic_id_param(self):
        self.assertEqual(resolve.parse_share_id("https://example.com/page?id=GEN456"), "GEN456")

    def test_bare_code(self):
        self.assertEqual(resolve.parse_share_id("abc_-123X"), "abc_-123X")

    def test_invalid_without_url_no_network(self):
        with self.assertRaises(resolve.InvalidLinkError):
            resolve.parse_share_id("这里什么链接都没有")

    def test_empty(self):
        with self.assertRaises(resolve.InvalidLinkError):
            resolve.parse_share_id("")


class TestParseCount(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(resolve.parse_count("255"), 255)
        self.assertEqual(resolve.parse_count("1.2万"), 12000)
        self.assertEqual(resolve.parse_count("10万+"), 100000)
        self.assertEqual(resolve.parse_count("1.5亿"), 150000000)
        self.assertEqual(resolve.parse_count("3,041"), 3041)
        self.assertEqual(resolve.parse_count(None), 0)
        self.assertEqual(resolve.parse_count(7), 7)
        self.assertEqual(resolve.parse_count("abc"), "abc")  # 转不了就原样返回


class TestExtractVideoUrl(unittest.TestCase):
    def test_priority_h264_then_h265_then_plain(self):
        self.assertEqual(
            resolve._extract_video_url({"h264VideoInfo": {"videoUrl": "a"}, "h265VideoInfo": {"videoUrl": "b"}}), "a"
        )
        self.assertEqual(resolve._extract_video_url({"h265VideoInfo": {"videoUrl": "b"}}), "b")
        self.assertEqual(resolve._extract_video_url({"videoUrl": "c"}), "c")
        self.assertIsNone(resolve._extract_video_url({}))


class TestBuildMeta(unittest.TestCase):
    FEED = {
        "errCode": 0,
        "data": {
            "feedInfo": {
                "description": "一条< br >测试文案",
                "coverUrl": "https://cdn.test/cover.jpg",
                "createtime": 1731945600,
                "likeCountFmt": "1.2万",
                "favCountFmt": "999",
                "forwardCountFmt": "10万+",
                "commentCountFmt": "3",
                "picInfo": [{"url": "https://cdn.test/p1.jpg"}],
            },
            "authorInfo": {"nickname": "测试作者"},
            "errMsg": {},
        },
    }

    def test_fields(self):
        meta = resolve.build_meta("AbC123", self.FEED)
        self.assertEqual(meta["id"], "AbC123")
        self.assertEqual(meta["share_url"], "https://weixin.qq.com/sph/AbC123")
        self.assertEqual(meta["author"], "测试作者")
        self.assertIn("测试文案", meta["description"])
        self.assertEqual(meta["interactions"]["like"], 12000)
        self.assertEqual(meta["interactions"]["forward"], 100000)
        self.assertEqual(meta["pic_count"], 1)
        self.assertIsNotNone(meta["create_time_iso"])
        self.assertNotIn("transcript_file", meta)


class TestAuth(unittest.TestCase):
    def test_parse_cookie_multiline(self):
        cmap = auth.parse_cookie("a=1;\r\nhy_user=u123\nhy_token=t456")
        self.assertEqual(cmap, {"a": "1", "hy_user": "u123", "hy_token": "t456"})

    def test_missing_fields(self):
        self.assertEqual(auth.missing_fields("hy_user=u"), ["hy_token"])
        self.assertEqual(auth.missing_fields("hy_user=u; hy_token=t"), [])

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[auth.ENV_STATE_DIR] = tmp
            try:
                path = auth.save_cookie("hy_user=u123; hy_token=t456")
                self.assertTrue(os.path.isfile(path))
                cookie, source = auth.load_cookie()
                self.assertEqual(cookie, "hy_user=u123; hy_token=t456")
                self.assertEqual(source, path)
            finally:
                del os.environ[auth.ENV_STATE_DIR]

    def test_save_rejects_incomplete(self):
        with self.assertRaises(ValueError):
            auth.save_cookie("hy_user=u123")


PUBLIC_FEED = {
    "errCode": 0,
    "data": {
        "feedInfo": {"description": "解析流程测试", "coverUrl": "https://cdn.test/cover.jpg"},
        "authorInfo": {"nickname": "作者"},
        "errMsg": {},
    },
}
PARSE_OK = {
    "code": 0,
    "data": {
        "playable_url": "https://channels.weixin.qq.com/finder-preview/pages/feed?token=TK123&eid=E456",
        "wx_export_id": "EXPORT9",
    },
}
PARSE_AUTH_FAIL = {"code": 20000, "error": {"code": 20000}, "msg": "未登录"}
FEED_OK = {
    "errCode": 0,
    "data": {
        "feedInfo": {
            "h264VideoInfo": {"videoUrl": "https://finder.video.qq.test/v.mp4?sig=1"},
            "h265VideoInfo": {"videoUrl": "https://finder.video.qq.test/v265.mp4"},
        },
        "errMsg": {},
    },
}


class TestResolveFlow(unittest.TestCase):
    """monkeypatch resolve._post_json，验证完整解析链路的 URL、payload 与结果。"""

    def setUp(self):
        self.calls = []

        def fake_post_json(url, payload, headers):
            self.calls.append((url, payload, headers))
            if "finder-preview/api/feed/get_feed_info" in url and payload.get("shortUri"):
                return PUBLIC_FEED
            if "yuanbao.tencent.com" in url:
                return PARSE_OK
            return FEED_OK

        self.patcher = mock.patch.object(resolve, "_post_json", side_effect=fake_post_json)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_full_flow_returns_h264_url(self):
        result = resolve.resolve("https://weixin.qq.com/sph/AbC123", cookie="hy_user=u123; hy_token=t456")
        self.assertEqual(result.video_url, "https://finder.video.qq.test/v.mp4?sig=1")
        self.assertEqual(result.cover_url, "https://cdn.test/cover.jpg")
        self.assertEqual(len(self.calls), 3)
        # 第二跳：元宝解析，payload 与鉴权头
        parse_url, parse_payload, parse_headers = self.calls[1]
        self.assertIn("get_parse_result", parse_url)
        self.assertEqual(parse_payload, {"type": "video_channel_url", "url": "https://weixin.qq.com/sph/AbC123", "scene": 1})
        self.assertEqual(parse_headers["X-Id"], "u123")
        self.assertEqual(parse_headers["T-Userid"], "u123")
        self.assertIn("hy_token=t456", parse_headers["Cookie"])
        # 第三跳：预览接口，带 token 和 exportId
        feed_url, feed_payload, _ = self.calls[2]
        self.assertIn("get_feed_info", feed_url)
        self.assertIn("_rid=", feed_url)
        self.assertEqual(feed_payload, {"baseReq": {"generalToken": "TK123"}, "exportId": "E456"})

    def test_without_cookie_meta_only(self):
        result = resolve.resolve("https://weixin.qq.com/sph/AbC123", cookie=None)
        self.assertIsNone(result.video_url)
        self.assertEqual(len(self.calls), 1)  # 只有公开预览一跳

    def test_expired_cookie_raises(self):
        def fake_post_json(url, payload, headers):
            if "yuanbao.tencent.com" in url:
                return PARSE_AUTH_FAIL
            return PUBLIC_FEED

        self.patcher.stop()
        with mock.patch.object(resolve, "_post_json", side_effect=fake_post_json):
            with self.assertRaises(resolve.LoginExpiredError):
                resolve.resolve("https://weixin.qq.com/sph/AbC123", cookie="hy_user=u123; hy_token=old")

    def test_incomplete_cookie_rejected_before_parse(self):
        # 公开元数据那跳照常发生（匿名即可），但不会发元宝解析请求
        with self.assertRaises(resolve.LoginExpiredError):
            resolve.resolve("https://weixin.qq.com/sph/AbC123", cookie="hy_user=u123")
        self.assertEqual(len(self.calls), 1)
        self.assertIn("get_feed_info", self.calls[0][0])  # 只有公开预览一跳


class TestCliSmoke(unittest.TestCase):
    def test_sph_download_help(self):
        import subprocess
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "sph_download.py"), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("sph_download", proc.stdout)

    def test_login_help(self):
        import subprocess
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "login.py"), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--login", proc.stdout)


if __name__ == "__main__":
    unittest.main()
