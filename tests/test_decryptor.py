"""Tests for decryptor: password generation, detection, content check.

Run: pytest tests/test_decryptor.py -v
"""
from src.decryptor import (
    generate_password_candidates,
    detect_protection,
)
from src.utils import has_subscription_content


# ═══════════════════════════════════════════════════════════════
# generate_password_candidates
# ═══════════════════════════════════════════════════════════════

class TestGeneratePasswordCandidates:

    def test_aabb_count(self):
        """AABB pattern: 10 choices for a, 9 for b (a!=b) = 90."""
        candidates = generate_password_candidates("AABB")
        assert len(candidates) == 90

    def test_aabb_pattern(self):
        candidates = generate_password_candidates("AABB")
        for pwd in candidates:
            assert pwd[0] == pwd[1], f"{pwd} is not AABB"
            assert pwd[2] == pwd[3], f"{pwd} is not AABB"
            assert pwd[0] != pwd[2], f"{pwd} has same first and second pair"

    def test_aabb_contains_known(self):
        candidates = generate_password_candidates("AABB")
        assert "0011" in candidates
        assert "3344" in candidates
        # 6767 is ABAB, not AABB
        assert "7744" in candidates  # AABB example

    def test_abab_included_when_requested(self):
        candidates = generate_password_candidates("ABAB")
        assert "1122" in candidates  # ABAB pattern
        assert "0101" in candidates

    def test_all_includes_everything(self):
        candidates = generate_password_candidates("all")
        assert "0000" in candidates
        assert "9999" in candidates
        assert len(candidates) >= 10000

    def test_no_duplicates(self):
        candidates = generate_password_candidates("all")
        assert len(candidates) == len(set(candidates))


# ═══════════════════════════════════════════════════════════════
# detect_protection
# ═══════════════════════════════════════════════════════════════

class TestDetectProtection:

    def test_yudou_protected(self):
        html = '<input class="cl-input" placeholder="在此输入密码"><button class="cl-btn">解密</button>'
        assert detect_protection(html) is True

    def test_generic_password_input(self):
        html = '<input type="password" name="pwd">'
        assert detect_protection(html) is True

    def test_chinese_password_keyword_only(self):
        """Text-only '密码' without input field should NOT trigger."""
        html = '<div>请输入密码查看内容</div>'
        assert detect_protection(html) is False

    def test_unprotected_page(self):
        html = '<div>免费节点订阅链接: https://example.com/v2ray.txt</div>'
        assert detect_protection(html) is False

    def test_case_insensitive(self):
        html = '<input type="Password" name="key">'
        assert detect_protection(html) is True

    def test_clash_in_text_not_protection(self):
        """'clash' in text without input field is NOT a protection indicator."""
        html = '<div>clash免费节点</div>'
        assert detect_protection(html) is False


# ═══════════════════════════════════════════════════════════════
# _has_subscription_content
# ═══════════════════════════════════════════════════════════════

class TestHasSubscriptionContent:

    def test_txt_link(self):
        assert has_subscription_content("", "https://example.com/node.txt") is True

    def test_yaml_link(self):
        assert has_subscription_content("", "https://example.com/config.yaml") is True

    def test_vmess_link(self):
        assert has_subscription_content("vmess://eyJ2IjoiMiI6ICJhYmNk...", "") is True

    def test_vless_link(self):
        assert has_subscription_content("vless://abc@1.2.3.4:443", "") is True

    def test_trojan_link(self):
        assert has_subscription_content("trojan://pass@1.2.3.4:443", "") is True

    def test_ss_link(self):
        assert has_subscription_content("ss://YWVzLTI1Ni1nY206d2MvZXFSUHJZ", "") is True

    def test_chinese_keyword_in_text(self):
        """'订阅链接' text alone should NOT trigger (no actual URL)."""
        assert has_subscription_content("订阅链接地址：https://example.com/sub.txt", "") is True

    def test_clash_keyword_in_text(self):
        """'Clash' text alone should NOT trigger (too broad)."""
        assert has_subscription_content("Clash 订阅配置文件", "") is False

    def test_no_content(self):
        assert has_subscription_content("", "<html>普通网页内容</html>") is False

    def test_empty(self):
        assert has_subscription_content("", "") is False
