# -*- coding: utf-8 -*-
"""
GeminiProvider 消息格式适配单元测试

覆盖：
- system message 提取与合并为 system_instruction
- system role 不会出现在 contents 中
- 普通 role 映射（assistant/model -> model，user -> user）
- 未知 role 跳过 + warning，不升级为 model
- 相邻同角色 Content 合并、图片 Part 顺序保留
- PromptService runtime_context(user) -> final system -> current user 的转换表现
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.chat.services.ai.providers.gemini_provider import GeminiProvider
from src.chat.services.ai.providers.base import GenerationConfig


def make_provider() -> GeminiProvider:
    """构造一个不依赖真实密钥/网络的 provider 实例"""
    return GeminiProvider(api_key="test-key", use_key_rotation=False)


def part_texts(content) -> list:
    """提取 Content 中所有非空文本 part"""
    texts = []
    for part in content.parts or []:
        text = getattr(part, "text", None)
        if text is not None:
            texts.append(text)
    return texts


class TestSystemTextExtraction(unittest.TestCase):
    """system message 提取 helper"""

    def test_extract_system_text_supports_content_str(self):
        provider = make_provider()
        messages = [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
        ]
        self.assertEqual(provider._extract_system_text(messages), "你是助手")

    def test_extract_system_text_supports_parts_list_str(self):
        provider = make_provider()
        messages = [{"role": "system", "parts": ["第一段", "第二段"]}]
        self.assertEqual(provider._extract_system_text(messages), "第一段\n第二段")

    def test_extract_system_text_supports_parts_dict_text(self):
        provider = make_provider()
        messages = [{"role": "system", "parts": [{"text": "hello"}]}]
        self.assertEqual(provider._extract_system_text(messages), "hello")

    def test_extract_system_text_supports_content_dict_text(self):
        provider = make_provider()
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "core"}]}
        ]
        self.assertEqual(provider._extract_system_text(messages), "core")

    def test_core_system_and_final_system_merged_in_order(self):
        provider = make_provider()
        messages = [
            {"role": "system", "content": "core 系统指令"},
            {"role": "user", "content": "u1"},
            {"role": "system", "content": "final 系统指令"},
        ]
        self.assertEqual(
            provider._extract_system_text(messages), "core 系统指令\n\nfinal 系统指令"
        )

    def test_no_system_message_returns_empty(self):
        provider = make_provider()
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "回复"},
        ]
        self.assertEqual(provider._extract_system_text(messages), "")


class TestSystemRoleNotInContents(unittest.TestCase):
    """system role 不出现在 contents 中，也不作为 model history"""

    def test_system_not_in_contents(self):
        provider = make_provider()
        messages = [
            {"role": "system", "content": "系统指令"},
            {"role": "user", "content": "你好"},
        ]
        contents = provider._convert_messages_to_contents(messages)
        self.assertNotIn("system", [c.role for c in contents])
        self.assertEqual([c.role for c in contents], ["user"])
        self.assertEqual(part_texts(contents[0]), ["你好"])

    def test_system_text_never_as_model_history(self):
        provider = make_provider()
        messages = [
            {"role": "system", "content": "秘密系统指令"},
            {"role": "assistant", "content": "模型回复"},
            {"role": "user", "content": "用户消息"},
        ]
        contents = provider._convert_messages_to_contents(messages)
        # 只有 model 和 user，没有 system
        self.assertEqual([c.role for c in contents], ["model", "user"])
        # system 文本绝不出现在任何 model/user part 中
        all_texts = [t for c in contents for t in part_texts(c)]
        self.assertNotIn("秘密系统指令", all_texts)


class TestGenerateSystemInstruction(unittest.IsolatedAsyncioTestCase):
    """generate / generate_with_tools 配置 system_instruction"""

    def _stub_response(self):
        return SimpleNamespace(candidates=[], usage_metadata=None)

    def _stub_network(self, provider):
        provider.acquire_client = AsyncMock(return_value=(MagicMock(), "test-key"))
        provider.release_client = AsyncMock()
        provider._stream_generate = AsyncMock(return_value=self._stub_response())

    async def test_generate_sets_merged_system_instruction(self):
        provider = make_provider()
        self._stub_network(provider)
        messages = [
            {"role": "system", "content": "core"},
            {"role": "user", "content": "u"},
            {"role": "system", "content": "final"},
        ]

        await provider.generate(
            messages, config=GenerationConfig(), model="gemini-2.5-flash"
        )

        _, _, _, gen_config = provider._stream_generate.await_args.args
        self.assertEqual(gen_config.system_instruction, "core\n\nfinal")

    async def test_generate_keeps_system_instruction_unset_when_no_system(self):
        provider = make_provider()
        self._stub_network(provider)
        messages = [{"role": "user", "content": "你好"}]

        await provider.generate(
            messages, config=GenerationConfig(), model="gemini-2.5-flash"
        )

        _, _, _, gen_config = provider._stream_generate.await_args.args
        self.assertIsNone(gen_config.system_instruction)

    async def test_generate_with_tools_sets_system_instruction(self):
        provider = make_provider()
        self._stub_network(provider)
        messages = [
            {"role": "system", "content": "工具系统指令"},
            {"role": "user", "content": "调用工具"},
        ]

        result = await provider.generate_with_tools(
            messages, config=GenerationConfig(), model="gemini-2.5-flash"
        )

        _, _, _, gen_config = provider._stream_generate.await_args.args
        self.assertEqual(gen_config.system_instruction, "工具系统指令")
        self.assertIsNotNone(result.content)

    async def test_generate_excludes_system_from_streamed_contents(self):
        provider = make_provider()
        self._stub_network(provider)
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]

        await provider.generate(
            messages, config=GenerationConfig(), model="gemini-2.5-flash"
        )

        _, _, contents, _ = provider._stream_generate.await_args.args
        for content in contents:
            self.assertNotEqual(content.role, "system")
        self.assertEqual([c.role for c in contents], ["user"])


class TestRoleMapping(unittest.TestCase):
    """普通 role 映射"""

    def test_assistant_maps_to_model(self):
        provider = make_provider()
        messages = [{"role": "assistant", "content": "模型回复"}]
        contents = provider._convert_messages_to_contents(messages)
        self.assertEqual([c.role for c in contents], ["model"])

    def test_user_maps_to_user(self):
        provider = make_provider()
        messages = [{"role": "user", "content": "用户消息"}]
        contents = provider._convert_messages_to_contents(messages)
        self.assertEqual([c.role for c in contents], ["user"])

    def test_model_role_maps_to_model(self):
        provider = make_provider()
        messages = [{"role": "model", "content": "已有模型消息"}]
        contents = provider._convert_messages_to_contents(messages)
        self.assertEqual([c.role for c in contents], ["model"])

    def test_unknown_role_not_upgraded_to_model(self):
        provider = make_provider()
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": "工具结果"},
            {"role": "unknown", "content": "未知消息"},
            {"role": "user", "content": "正常用户"},
        ]
        contents = provider._convert_messages_to_contents(messages)
        # 未知角色被跳过，不会变成 model，也不出现在结果中
        self.assertEqual([c.role for c in contents], ["user"])
        self.assertEqual(part_texts(contents[0]), ["正常用户"])


class TestAdjacentRoleMerging(unittest.TestCase):
    """相邻同角色 Content 合并"""

    def test_consecutive_user_merged_parts_in_order(self):
        provider = make_provider()
        messages = [
            {"role": "user", "content": "u1"},
            {"role": "user", "content": "u2"},
            {"role": "user", "content": "u3"},
        ]
        contents = provider._convert_messages_to_contents(messages)
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0].role, "user")
        self.assertEqual(part_texts(contents[0]), ["u1", "u2", "u3"])

    def test_consecutive_model_merged(self):
        provider = make_provider()
        messages = [
            {"role": "assistant", "content": "m1"},
            {"role": "model", "content": "m2"},
        ]
        contents = provider._convert_messages_to_contents(messages)
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0].role, "model")
        self.assertEqual(part_texts(contents[0]), ["m1", "m2"])

    def test_alternating_roles_not_cross_merged(self):
        provider = make_provider()
        messages = [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "m1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "m2"},
        ]
        contents = provider._convert_messages_to_contents(messages)
        self.assertEqual([c.role for c in contents], ["user", "model", "user", "model"])
        self.assertEqual(part_texts(contents[0]), ["u1"])
        self.assertEqual(part_texts(contents[1]), ["m1"])
        self.assertEqual(part_texts(contents[2]), ["u2"])
        self.assertEqual(part_texts(contents[3]), ["m2"])

    def test_user_image_parts_preserved_after_merge(self):
        provider = make_provider()
        image_bytes = b"\x89PNG-fake-image-bytes"
        messages = [
            {"role": "user", "content": "看图"},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "image_bytes": image_bytes,
                        "mime_type": "image/png",
                    }
                ],
            },
        ]
        contents = provider._convert_messages_to_contents(messages)
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0].role, "user")

        parts = contents[0].parts
        # 文本 + 图片顺序保持不变
        self.assertEqual(parts[0].text, "看图")
        self.assertIsNotNone(parts[1].inline_data)
        self.assertEqual(parts[1].inline_data.mime_type, "image/png")
        self.assertEqual(parts[1].inline_data.data, image_bytes)


class TestPromptServiceScenario(unittest.TestCase):
    """
    PromptService 当前流程: runtime_context(user) -> final system -> current user

    Gemini 转换后应表现为：
    - system_instruction 包含 final system
    - contents 中 runtime/current user 按连续 user 归并规则安全存在
    - system 文本绝不作为 model history
    """

    def test_runtime_context_final_system_current_user(self):
        provider = make_provider()
        messages = [
            {"role": "user", "content": "runtime context 早期 user"},
            {"role": "system", "content": "final system 指令"},
            {"role": "user", "content": "current user 消息"},
        ]

        # system_instruction 只包含 final system
        self.assertEqual(provider._extract_system_text(messages), "final system 指令")

        # contents 中 system 不存在，连续 user 合并为一条
        contents = provider._convert_messages_to_contents(messages)
        self.assertNotIn("system", [c.role for c in contents])
        self.assertEqual([c.role for c in contents], ["user"])
        self.assertEqual(
            part_texts(contents[0]),
            ["runtime context 早期 user", "current user 消息"],
        )

        # system 文本绝不作为 model history
        all_texts = [t for c in contents for t in part_texts(c)]
        self.assertNotIn("final system 指令", all_texts)
        self.assertTrue(all(not t.startswith("final system") for t in all_texts))


if __name__ == "__main__":
    unittest.main()