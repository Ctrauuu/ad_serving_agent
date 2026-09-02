from app.services.auth import authenticate_user
from app.services.campaign import (
    create_campaign,
    get_campaign,
    list_campaigns,
    update_campaign,
)
from app.services.goal import parse_goal_text
from app.services.catalog import (
    list_audiences,
    list_channels,
    list_creatives,
    list_products,
)
from app.services.embedding import embed_goal
from app.services.strategy import (
    confirm_strategy,
    generate_strategy,
    get_latest_strategy,
)


__all__ = [
    "authenticate_user",
    "create_campaign",
    "get_campaign",
    "list_campaigns",
    "update_campaign",
    "parse_goal_text",
    "list_products",
    "list_channels",
    "list_audiences",
    "list_creatives",
    "embed_goal",
    "generate_strategy",
    "get_latest_strategy",
    "confirm_strategy",
]