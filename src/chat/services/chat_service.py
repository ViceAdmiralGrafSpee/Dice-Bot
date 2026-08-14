# -*- coding: utf-8 -*-

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

# 导入所需的服务
from src.config import BOT_NAME
from src.chat.services.ai.service import ai_service
from src.chat.platform import ConversationKind, PlatformRequestContext
from src.chat.utils.prompt_utils import replace_emojis
from src.chat.services.prompt_service import prompt_service
from src.chat.features.world_book.services.world_book_service import world_book_service
from src.chat.features.affection.service.affection_service import affection_service
from src.chat.features.odysseia_coin.service.coin_service import coin_service
from src.chat.utils.database import chat_db_manager
from src.chat.features.personal_memory.services.personal_memory_service import (
    personal_memory_service,
)
from src.chat.features.personal_memory.services.user_memory_note_service import (
    user_memory_note_service,
)
from src.chat.config import chat_config
from src.chat.config.chat_config import DEBUG_CONFIG
from src.chat.features.chat_settings.services.chat_settings_service import (
    chat_settings_service,
)
from src.chat.services.ai.providers.base import GenerationConfig
from src.chat.services.ai.providers.provider_format import ProviderFormat, MessageFormat
from src.chat.services.persona_preference_service import persona_preference_service
from src.database.identity import platform_user_identity
from src.database.services.member_profile_service import member_profile_service

log = logging.getLogger(__name__)


@dataclass
class ChatResult:
    """
    聊天响应结果，包含回复内容和工具调用元数据。

    Attributes:
        content: AI 生成的回复文本
        tools_called: 本次请求中 AI 调用过的工具名称列表
    """

    content: str
    tools_called: List[str] = field(default_factory=list)
    authoritative_outputs: List[str] = field(default_factory=list)


class ChatService:
    """
    负责编排整个AI聊天响应流程。
    """

    def __init__(self) -> None:
        # Discord deployments historically require PostgreSQL. Lightweight
        # adapters can explicitly disable these optional legacy features.
        self._optional_postgres_enabled = True

    def set_optional_postgres_enabled(self, enabled: bool) -> None:
        self._optional_postgres_enabled = enabled
        if not enabled:
            log.info("未检测到完整 PostgreSQL 数据库；已跳过档案、记忆、好感度和币功能。")

    async def _load_optional_user_context(
        self,
        platform: str,
        user_id: str,
        user_name: str,
        numeric_user_id: int,
    ) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
        """Load PostgreSQL-backed context, or use neutral chat defaults."""

        if not self._optional_postgres_enabled:
            return None, None, "default"

        try:
            identity = platform_user_identity(platform, user_id)
            await member_profile_service.ensure_minimal_profile(identity, user_name)
            profile = await world_book_service.get_profile_by_user_id(
                identity.database_key
            )
            affection = await affection_service.get_affection_status(numeric_user_id)
            persona = await persona_preference_service.get_persona_style(
                identity.database_key
            )
            return profile, affection, persona
        except Exception as error:
            log.warning(
                "PostgreSQL 用户功能暂时不可用，本条消息使用默认上下文：%s",
                error,
            )
            return None, None, "default"

    async def should_process_message(
        self, request: PlatformRequestContext
    ) -> bool:
        """
        执行前置检查，判断消息是否应该被处理，以避免不必要的"输入中"状态。
        """
        message = request.message
        user_id = int(message.user_id)
        channel_id = int(message.conversation.conversation_id)
        guild_id = int(message.conversation.space_id or 0)

        # 1. 全局聊天开关检查
        if not await chat_settings_service.is_chat_globally_enabled(guild_id):
            log.info(f"服务器 {guild_id} 全局聊天已禁用，跳过前置检查。")
            return False

        # 2. 频道/分类设置检查
        effective_config = await request.get_effective_chat_config()

        if not effective_config.get("is_chat_enabled", True):
            # 检查是否满足通行许可的例外条件
            pass_is_granted = False
            thread = message.conversation.thread
            if self._optional_postgres_enabled and thread and thread.owner_id:
                # 修正逻辑：只有当帖主明确设置了个人CD时，才算拥有"通行许可"
                owner_id = int(thread.owner_id)
                owner_config = await coin_service.get_thread_cooldown_settings(owner_id)

                if owner_config:
                    has_personal_cd = owner_config[
                        "thread_cooldown_seconds"
                    ] is not None or (
                        owner_config["thread_cooldown_duration"] is not None
                        and owner_config["thread_cooldown_limit"] is not None
                    )
                    if has_personal_cd:
                        pass_is_granted = True
                        log.info(
                            f"帖主 {owner_id} 拥有个人CD设置（通行许可），覆盖会话 {channel_id} 的聊天限制。"
                        )

            # 如果没有授予通行权，则按原逻辑返回 False
            if not pass_is_granted:
                log.info(f"会话 {channel_id} 聊天已禁用，跳过前置检查。")
                return False

        # 3. 新版冷却时间检查
        if await chat_settings_service.is_user_on_cooldown(
            user_id, channel_id, effective_config
        ):
            log.info(
                f"用户 {user_id} 在会话 {channel_id} 处于新版冷却状态，跳过前置检查。"
            )
            return False

        # 冷却检查通过后立即更新冷却时间戳，防止用户在AI处理期间重复调用
        await chat_settings_service.update_user_cooldown(
            user_id, channel_id, effective_config
        )

        # 4. 黑名单检查
        if await chat_db_manager.is_user_blacklisted(user_id, guild_id):
            log.info(f"用户 {user_id} 在空间 {guild_id} 被拉黑，跳过前置检查。")
            return False

        return True

    async def handle_chat_message(
        self,
        request: PlatformRequestContext,
    ) -> Optional[ChatResult]:
        """
        处理聊天消息，生成并返回AI的最终回复。

        Args:
            request: 标准消息以及由平台外层提供的必要操作。

        Returns:
            ChatResult: AI生成的回复结果（含工具调用元数据）。如果为 None，则表示不应回复。
        """
        message = request.message
        user_id = message.user_id
        memory_user_id = platform_user_identity(
            message.platform, message.user_id
        ).database_key
        numeric_user_id = int(user_id)
        user_name = message.user_name
        guild_name = message.conversation.space_name or "私信"

        if message.conversation.kind is ConversationKind.THREAD:
            parent_name = (
                message.conversation.thread.parent_name
                if message.conversation.thread
                else None
            )
            location_name = f"{parent_name or '未知频道'} -> {message.conversation.name}"
        elif message.conversation.kind is ConversationKind.DIRECT:
            location_name = "私信中"
        else:
            location_name = message.conversation.name

        # PostgreSQL 是可选增强项；无数据库时仍可进行基础 AI 对话。
        (
            user_profile_data,
            affection_status,
            persona_style,
        ) = await self._load_optional_user_context(
            message.platform,
            user_id,
            user_name,
            numeric_user_id,
        )

        user_content = message.text
        replied_content = (
            message.replied_message.text if message.replied_message else ""
        )
        image_data_list = [
            {
                "mime_type": image.mime_type,
                "data": image.data,
                "source": image.source,
                "name": image.name,
            }
            for image in message.images
        ]
        authoritative_outputs: List[str] = []
        called_tools: List[str] = []

        try:
            # 2. --- 上下文与知识库检索 ---
            # 获取频道历史上下文
            channel_context = await request.get_formatted_history()

            # 构建备用搜索查询（供 gather_context 工具使用）
            rag_query = user_content
            if replied_content:
                rag_query = f"{replied_content}\n{user_content}"

            # 确保对话块在工具检索前创建（副作用必须保留）
            if user_profile_data:
                await personal_memory_service.check_and_create_block_before_reply(
                    user_id=memory_user_id
                )

            # 获取记忆笔记（仅对有名片用户）
            memory_notes_text = None
            if user_profile_data:
                try:
                    memory_notes_text = await user_memory_note_service.get_notes_for_context(
                        memory_user_id
                    )
                except Exception as mem_note_e:
                    log.error(f"获取用户 {user_id} 记忆笔记失败: {mem_note_e}")

            # 获取最近聊天历史（仅对有名片用户，1-10条递增）
            recent_chat_history = None
            if user_profile_data:
                try:
                    recent_chat_history = await personal_memory_service.get_recent_chat_history(
                        memory_user_id, limit=10
                    )
                except Exception as hist_e:
                    log.error(f"获取用户 {user_id} 最近聊天历史失败: {hist_e}")

            # 3. --- 好感度与奖励更新（前置） ---
            if self._optional_postgres_enabled:
                try:
                    # 在生成回复前更新好感度，以确保日志顺序正确
                    await affection_service.increase_affection_on_message(
                        numeric_user_id
                    )
                except Exception as aff_e:
                    log.error(f"增加用户 {user_id} 的好感度时出错: {aff_e}")

                try:
                    # 发放每日首次对话奖励
                    if await coin_service.grant_daily_message_reward(numeric_user_id):
                        log.info(f"已为用户 {user_id} 发放每日首次对话奖励。")
                except Exception as coin_e:
                    log.error(f"为用户 {user_id} 发放每日对话奖励时出错: {coin_e}")

            # 4. --- 调用AI生成回复 ---
            # 记录发送给AI的核心上下文
            if DEBUG_CONFIG["LOG_FINAL_CONTEXT"]:
                log.info(f"发送给AI -> 最终上下文: {channel_context}")

            # --- 获取当前设置的AI模型 ---
            current_model = await chat_settings_service.get_current_ai_model()
            log.info(f"当前使用的AI模型: {current_model}")

            # --- 两阶段回复管线配置 ---
            two_stage_on = await chat_settings_service.is_two_stage_enabled()
            tool_model_id = (
                await chat_settings_service.get_tool_model() if two_stage_on else None
            )
            writer_model_id = (
                await chat_settings_service.get_writer_model() if two_stage_on else None
            )
            if two_stage_on:
                log.info(
                    f"[两阶段] 已启用：工具模型={tool_model_id}，写作模型={writer_model_id}"
                )

            # --- [新增] 根据上下文确定用于工具设置的用户ID ---
            user_id_for_settings: Optional[str] = None
            thread = message.conversation.thread
            if thread and thread.owner_id:
                user_id_for_settings = thread.owner_id
                log.info(
                    f"消息在帖子中，将使用帖主 {user_id_for_settings} 的工具设置。"
                )
            else:
                log.info("消息不在帖子中，将使用默认工具集。")
            # --- [结束] ---

            # --- 解析 Provider 类型 ---
            def _resolve_provider_type(model_id: str) -> str:
                m_name, explicit_prov = ai_service.parse_model_id(model_id)
                prov = ai_service.get_provider_for_model(m_name, explicit_prov)
                return prov.provider_type if prov else ""

            def _output_format_for(p_type: str) -> str:
                mf = ProviderFormat.get_message_format(p_type)
                return "openai" if mf == MessageFormat.OPENAI else "gemini"

            writer_provider_type = ""
            if two_stage_on:
                # 工具格式跟随 Stage 1（工具模型）；消息人设格式跟随 Stage 2（写作模型）
                provider_type = _resolve_provider_type(
                    tool_model_id or current_model
                )
                writer_provider_type = _resolve_provider_type(
                    writer_model_id or current_model
                )
                output_format = _output_format_for(writer_provider_type)
            else:
                provider_type = _resolve_provider_type(current_model)
                output_format = _output_format_for(provider_type)

            log.info(
                f"[Provider 映射调试] two_stage={two_stage_on}, "
                f"provider_type(工具)={repr(provider_type)}, "
                f"writer_provider_type="
                f"{repr(writer_provider_type) if two_stage_on else 'N/A'}"
            )

            # 使用 PromptService 构建消息
            # （两阶段模式下，此 messages 作为 Stage 2 的完整人设提示）
            # 注意：build_chat_prompt / get_generation_config 按裸模型名查配置，
            # 因此这里传入去掉 provider 前缀的裸名。
            _prompt_model_name = current_model
            if two_stage_on and writer_model_id:
                _prompt_model_name, _ = ai_service.parse_model_id(writer_model_id)
            messages = await prompt_service.build_chat_prompt(
                user_name=user_name,
                message=user_content,
                replied_message=replied_content,
                images=image_data_list if image_data_list else None,
                channel_context=channel_context,
                world_book_entries=None,
                affection_status=affection_status,
                guild_name=guild_name,
                location_name=location_name,
                personal_summary=None,
                user_profile_data=user_profile_data,
                model_name=_prompt_model_name,
                conversation=message.conversation,
                conversation_memory=None,
                latest_block=None,
                output_format=output_format,
                persona_style=persona_style,
                memory_notes=memory_notes_text,
                recent_chat_history=recent_chat_history,
            )

            # Stage 1：极简工具路由提示（无人设、无世界书、无好感度、无历史，最大化缓存命中）
            stage1_messages: Optional[List[Dict[str, Any]]] = None
            if two_stage_on:
                stage1_messages = [
                    {
                        "role": "system",
                        "content": chat_config.TOOL_ROUTER_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": user_content},
                ]

            # 获取工具列表（根据 Provider 类型返回对应格式）
            tools = await ai_service.tool_service.get_dynamic_tools_for_context(
                user_id_for_settings, provider_type=provider_type
            )

            # 定义工具执行器（使用闭包追踪本次请求中调用的工具）
            _search_scopes: List[str] = []
            _captured_tool_records: List[Dict[str, Any]] = []

            async def tool_executor(call, **kwargs):
                # 记录被调用的工具名称（兼容 dict 和 FunctionCall 对象）
                if isinstance(call, dict):
                    name = call.get("name", "")
                    args = call.get("arguments", {})
                else:
                    name = getattr(call, "name", "")
                    args = dict(call.args) if call.args else {}
                called_tools.append(name)
                if name == "search":
                    _search_scopes.append(args.get("scope", ""))
                part = await request.execute_tool_call(
                    ai_service.tool_service,
                    call,
                    user_id=user_id,
                    user_id_for_settings=user_id_for_settings,
                    user_name=user_name,
                    platform=message.platform,
                    fallback_query=rag_query,
                    channel_context=channel_context,
                )
                # 捕获工具调用记录（供两阶段 Stage 2 使用）
                if isinstance(part, dict):
                    captured_response = part
                else:
                    func_resp = getattr(part, "function_response", None)
                    captured_response = getattr(func_resp, "response", None) or {}
                    captured_response = dict(captured_response)
                authoritative_output = captured_response.get(
                    "authoritative_output"
                )
                if isinstance(authoritative_output, str) and authoritative_output:
                    if authoritative_output not in authoritative_outputs:
                        authoritative_outputs.append(authoritative_output)
                _captured_tool_records.append(
                    {
                        "name": name,
                        "arguments": args,
                        "response": captured_response,
                    }
                )
                return part

            # 创建生成配置（从数据库获取模型参数）
            # 两阶段模式下以写作模型（Stage 2）的参数为准
            from src.chat.services.ai.config.models import get_generation_config

            config_model = writer_model_id or current_model
            # get_generation_config 按裸模型名查配置，去掉可能的 provider 前缀
            _config_bare, _ = ai_service.parse_model_id(config_model)
            gen_params = get_generation_config(_config_bare)
            log.debug(
                f"模型 {config_model} 生成参数: "
                f"temperature={gen_params.temperature}, "
                f"top_p={gen_params.top_p}, top_k={gen_params.top_k}, "
                f"max_output_tokens={gen_params.max_output_tokens}, "
                f"thinking_budget_tokens={gen_params.thinking_budget_tokens}"
            )
            generation_config = GenerationConfig(
                temperature=gen_params.temperature,
                top_p=gen_params.top_p,
                top_k=gen_params.top_k,
                max_output_tokens=gen_params.max_output_tokens,
                presence_penalty=gen_params.presence_penalty,
                frequency_penalty=gen_params.frequency_penalty,
                thinking_budget_tokens=gen_params.thinking_budget_tokens,
            )

            # 调用 AIService
            if two_stage_on:
                result = await ai_service.generate_two_stage(
                    stage1_messages=stage1_messages or [],
                    stage2_messages=messages,
                    config=generation_config,
                    tool_model=tool_model_id,
                    writer_model=writer_model_id,
                    tools=tools,
                    tool_executor=tool_executor,
                    captured_tool_records=_captured_tool_records,
                    user_id_for_settings=user_id_for_settings,
                )
            else:
                result = await ai_service.generate_with_tools(
                    messages=messages,
                    config=generation_config,
                    model=current_model,
                    tools=tools,
                    tool_executor=tool_executor,
                    user_id_for_settings=user_id_for_settings,
                )

            # 记录模型使用统计
            # 两阶段模式下记录工具模型与写作模型两次调用
            stat_models = (
                [tool_model_id, writer_model_id] if two_stage_on else [current_model]
            )
            for _stat_model_id in stat_models:
                if not _stat_model_id:
                    continue
                _model_name, _explicit_provider = ai_service.parse_model_id(
                    _stat_model_id
                )
                if _explicit_provider:
                    _provider_name = _explicit_provider
                else:
                    _provider_name = ai_service._model_to_provider.get(
                        _model_name, "unknown"
                    )
                await chat_settings_service.increment_model_usage(
                    model_name=_model_name, provider_name=_provider_name
                )
                log.debug(
                    f"记录模型使用: {_model_name} (Provider: {_provider_name})"
                )

            ai_response = result.content

            # Python 会在最终回复开头展示一份权威工具结果。模型有时会先把同一
            # 骰子式再抄一遍（例如“🎲 1d6 = 2”），这里仅移除这种独立成行的
            # 开头复述，保留后续的人格化说明。
            if ai_response and authoritative_outputs:
                ai_response = self._remove_repeated_authoritative_result_lines(
                    ai_response,
                    _captured_tool_records,
                )

            if not ai_response and not authoritative_outputs:
                log.warning(f"AI服务未返回回复（重试+故障转移均失败），跳过用户 {user_id}。")
                return None

            # --- 新增：调用新的个人记忆服务 ---
            # 在获得AI回复后，记录这次对话并根据需要触发总结
            # 传递 current_model 使总结逻辑跟随主模型
            if user_profile_data and ai_response:
                try:
                    await personal_memory_service.update_and_conditionally_summarize_memory(
                        user_id=memory_user_id,
                        user_name=user_name,
                        user_content=user_content,
                        ai_response=ai_response,
                        current_model=current_model,
                    )
                except Exception as mem_e:
                    log.error(
                        f"[ChatService] 用户 {user_id} 对话块总结失败，跳过: {mem_e}",
                        exc_info=True,
                    )

            # 5. --- 后处理与格式化 ---
            final_response = self._format_ai_response(ai_response) if ai_response else ""

            # 数值和规则结算由 Python 锁定。LLM 只负责后续表述，不能覆盖结果。
            if authoritative_outputs:
                authoritative_block = "\n".join(authoritative_outputs)
                final_response = (
                    f"{authoritative_block}\n\n{final_response}"
                    if final_response
                    else authoritative_block
                )

            # --- 为特定工具调用添加后缀 ---
            if _search_scopes and any(
                scope == "tutorial" for scope in _search_scopes
            ):
                final_response += chat_config.TUTORIAL_SEARCH_SUFFIX

            # 6. --- 异步执行后续任务（不阻塞回复） ---
            # 此处现在只应包含不影响核心回复流程的日志记录等任务
            # self._log_rag_summary(user_id, user_name, user_content, [], final_response)

            log.info(f"已为用户 {user_name} 生成AI回复: {final_response}")
            return ChatResult(
                content=final_response,
                tools_called=called_tools,
                authoritative_outputs=authoritative_outputs,
            )

        except Exception as e:
            log.error(f"[ChatService] 处理聊天消息时出错: {e}", exc_info=True)
            if authoritative_outputs:
                return ChatResult(
                    content=(
                        "\n".join(authoritative_outputs)
                        + "\n\n（骰子结果已生成，但 AI 表述暂时失败。）"
                    ),
                    tools_called=called_tools,
                    authoritative_outputs=authoritative_outputs,
                )
            return ChatResult(content="抱歉，处理你的消息时出现了问题，请稍后再试。")

    @staticmethod
    def _remove_repeated_authoritative_result_lines(
        ai_response: str,
        captured_tool_records: List[Dict[str, Any]],
    ) -> str:
        """移除模型在回复开头重复输出的 Python 权威结果行。"""
        dice_results: List[tuple[str, str]] = []
        exact_outputs: List[str] = []
        for record in captured_tool_records:
            response = record.get("response")
            if not isinstance(response, dict):
                continue
            authoritative_output = response.get("authoritative_output")
            if isinstance(authoritative_output, str) and authoritative_output:
                exact_outputs.append(authoritative_output)
            if record.get("name") != "roll_dice":
                continue
            result = response.get("result")
            if not isinstance(result, dict):
                continue
            notation = result.get("notation")
            total = result.get("total")
            if isinstance(notation, str) and isinstance(total, (int, float)):
                dice_results.append((notation, str(total)))

        if not dice_results and not exact_outputs:
            return ai_response

        def normalize(line: str) -> str:
            normalized = "".join(line.lower().split()).strip("*_`")
            return normalized.rstrip("。.!！*_`")

        normalized_exact_outputs = {normalize(output) for output in exact_outputs}

        def is_repeated_result_line(line: str) -> bool:
            normalized = normalize(line)
            if normalized in normalized_exact_outputs:
                return True
            if normalized.startswith("🎲"):
                normalized = normalized[1:].strip("*_`")
            return any(
                normalized.startswith(
                    f"{''.join(notation.lower().split())}="
                )
                and normalized.endswith(f"={total}")
                for notation, total in dice_results
            )

        lines = ai_response.splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and is_repeated_result_line(lines[0]):
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)
        return "\n".join(lines).lstrip()

    def _format_ai_response(self, ai_response: str) -> str:
        """清理和格式化AI的原始回复。"""
        # 移除可能包含的自身名字前缀
        bot_name_prefix = f"{BOT_NAME}:"
        if ai_response.startswith(bot_name_prefix):
            ai_response = ai_response[len(bot_name_prefix) :].lstrip()
        # 将多段回复的双换行符替换为单换行符
        formatted_response = ai_response.replace("\n\n", "\n")
        # 转换表情包占位符为Discord自定义表情
        formatted_response = replace_emojis(formatted_response)
        return formatted_response

    async def _perform_post_response_tasks(
        self,
        user_id: str | int,
        user_name: str,
        guild_id: int,
        query: str,
        rag_entries: list,
        response: str,
    ):
        """执行发送回复后的任务，如记录日志。"""
        # 好感度和奖励逻辑已前置，此处保留用于未来可能的其他后处理任务

        # 记录 RAG 诊断日志
        # self._log_rag_summary(user_id, user_name, query, rag_entries, response)
        pass

    def _log_rag_summary(
        self,
        user_id: str | int,
        user_name: str,
        query: str,
        entries: list,
        response: str,
    ):
        """生成并记录 RAG 诊断摘要日志。"""
        try:
            if entries:
                doc_details = []
                for entry in entries:
                    distance = entry.get("distance", "N/A")
                    distance_str = (
                        f"{distance:.4f}"
                        if isinstance(distance, (int, float))
                        else str(distance)
                    )
                    content = str(entry.get("content", "N/A")).replace("\n", "\n    ")
                    doc_details.append(
                        f"  - Doc ID: {entry.get('id', 'N/A')}, Distance: {distance_str}\n"
                        f"    Content: {content}"
                    )
                retrieved_docs_summary = "\n" + "\n".join(doc_details)
            else:
                retrieved_docs_summary = " N/A"

            summary_log_message = (
                f"\n--- RAG DIAGNOSTIC SUMMARY ---\n"
                f"User: {user_name} ({user_id})\n"
                f'Initial Query: "{query}"\n'
                f"Retrieved Docs:{retrieved_docs_summary}\n"
                f'Final AI Response: "{response}"\n'
                f"------------------------------"
            )
            log.info(summary_log_message)
        except Exception as log_e:
            log.error(f"生成 RAG 诊断摘要日志时出错: {log_e}")


# 创建一个单例
chat_service = ChatService()
