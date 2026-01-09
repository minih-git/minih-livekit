"""
SIP 配置服务
在 Agent 启动时自动创建 SIP Inbound Trunk 和 Dispatch Rule
"""

import os
import logging
from livekit import api

logger = logging.getLogger("services.sip_setup")


async def setup_sip_trunk() -> None:
    """
    设置 SIP Trunk 和 Dispatch Rule

    幂等操作：如果 Trunk 或 Rule 已存在，则跳过创建

    环境变量配置：
    - SIP_TRUNK_NAME: Inbound Trunk 名称，默认 "minih-default-trunk"
    - SIP_DISPATCH_RULE_NAME: Dispatch Rule 名称，默认 "minih-dispatch-rule"
    - SIP_ROOM_PREFIX: 房间名称前缀，默认 "sip-"
    - AGENT_NAME: 调度的 Agent 名称（复用现有环境变量）
    """
    # 获取配置
    trunk_name = os.environ.get("SIP_TRUNK_NAME", "minih-default-trunk")
    rule_name = os.environ.get("SIP_DISPATCH_RULE_NAME", "minih-dispatch-rule")
    room_prefix = os.environ.get("SIP_ROOM_PREFIX", "sip-")
    agent_name = os.environ.get("AGENT_NAME", "minih-dev-worker")

    livekit_url = os.environ.get("LIVEKIT_URL")
    api_key = os.environ.get("LIVEKIT_API_KEY")
    api_secret = os.environ.get("LIVEKIT_API_SECRET")

    if not all([livekit_url, api_key, api_secret]):
        logger.warning("⚠️ 缺少 LiveKit 环境变量，跳过 SIP 配置")
        return

    logger.info(f"🔧 开始配置 SIP Trunk: {trunk_name}")

    try:
        # 初始化 LiveKit API
        lk_api = api.LiveKitAPI(
            url=livekit_url,
            api_key=api_key,
            api_secret=api_secret,
        )

        # ========== 1. 创建 Inbound Trunk ==========
        trunk_id = await _ensure_inbound_trunk(lk_api, trunk_name)

        # ========== 2. 创建 Dispatch Rule ==========
        await _ensure_dispatch_rule(
            lk_api, rule_name, room_prefix, agent_name, trunk_id
        )

        # 清理
        await lk_api.aclose()

        logger.info("✅ SIP 配置完成")

    except Exception as e:
        logger.error(f"❌ SIP 配置失败: {e}")
        raise


async def _ensure_inbound_trunk(lk_api: api.LiveKitAPI, trunk_name: str) -> str:
    """
    确保 Inbound Trunk 存在，返回 trunk_id
    """
    # 查询已存在的 Trunk
    existing_trunks = await lk_api.sip.list_sip_inbound_trunk(
        api.ListSIPInboundTrunkRequest()
    )

    # 检查是否已存在同名 Trunk
    for trunk in existing_trunks.items:
        if trunk.name == trunk_name:
            logger.info(f"ℹ️ SIP Inbound Trunk 已存在: {trunk.sip_trunk_id}")
            return trunk.sip_trunk_id

    # 创建新 Trunk
    # 安全要求：必须设置 AuthUsername+AuthPassword、AllowedAddresses 或 Numbers 之一
    # 开发环境：使用通配符地址允许所有来源
    trunk_info = api.SIPInboundTrunkInfo(
        name=trunk_name,
        # 允许所有 IP 地址（开发环境配置）
        # 生产环境应限制为 SIP 提供商的 IP 地址
        allowed_addresses=["0.0.0.0/0"],
    )

    result = await lk_api.sip.create_sip_inbound_trunk(
        api.CreateSIPInboundTrunkRequest(trunk=trunk_info)
    )

    logger.info(f"✅ SIP Inbound Trunk 已创建: {result.sip_trunk_id}")
    return result.sip_trunk_id


async def _ensure_dispatch_rule(
    lk_api: api.LiveKitAPI,
    rule_name: str,
    room_prefix: str,
    agent_name: str,
    trunk_id: str,
) -> None:
    """
    确保 Dispatch Rule 存在
    """
    # 查询已存在的 Rule
    existing_rules = await lk_api.sip.list_sip_dispatch_rule(
        api.ListSIPDispatchRuleRequest()
    )

    # 检查是否已存在同名 Rule
    for rule in existing_rules.items:
        if rule.name == rule_name:
            logger.info(f"ℹ️ SIP Dispatch Rule 已存在: {rule.sip_dispatch_rule_id}")
            return

    # 创建新 Rule - 使用 Individual 模式，每个呼叫创建独立房间
    dispatch_rule = api.SIPDispatchRuleIndividual(
        room_prefix=room_prefix,
    )

    # 通过 room_config 配置 Agent 调度
    room_config = api.RoomConfiguration(
        agents=[
            api.RoomAgentDispatch(agent_name=agent_name),
        ],
    )

    # CreateSIPDispatchRuleRequest 直接接受字段，不需要包装成 SIPDispatchRuleInfo
    result = await lk_api.sip.create_sip_dispatch_rule(
        api.CreateSIPDispatchRuleRequest(
            name=rule_name,
            trunk_ids=[trunk_id],
            rule=api.SIPDispatchRule(
                dispatch_rule_individual=dispatch_rule,
            ),
            room_config=room_config,
        )
    )

    logger.info(f"✅ SIP Dispatch Rule 已创建: {result.sip_dispatch_rule_id}")
