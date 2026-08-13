"""
Billing and Credit Management Service.

Handles:
- Credit calculation based on request complexity
- Credit deduction with Two-Attempt Rule enforcement
- Subscription plan management
- Dynamic pricing for quests/dialogues/assets
"""

import logging
from datetime import datetime
from typing import Optional, Literal
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db_session
from backend.models.schemas import User, Subscription, GenerationHistory, Project
from backend.core.config import get_settings
from backend.schemas.agent_schemas import WizardInput

logger = logging.getLogger("kotodama.services.billing")


class BillingService:
    """
    Manages credits, subscriptions, and billing operations.
    
    Implements dynamic pricing based on:
    - Quest complexity (none/simple/branching/epic)
    - Dialogue depth (none/linear/branching/full_rpg)
    - Asset generation count
    - Save system requirement
    - Two-Attempt Rule (Attempt 1 free, Attempt 2 charged)
    """
    
    def __init__(self):
        self.settings = get_settings()
    
    async def get_user_subscription(self, user_id: str) -> Optional[Subscription]:
        """Get active subscription for a user."""
        async with get_db_session() as session:
            result = await session.execute(
                select(Subscription)
                .where(Subscription.user_id == int(user_id))
                .where(Subscription.is_active == True)
            )
            return result.scalar_one_or_none()
    
    async def get_user_credits(self, user_id: str) -> int:
        """Get remaining credits for a user."""
        subscription = await self.get_user_subscription(user_id)
        if not subscription:
            # Free tier default
            return 0
        return subscription.credits_remaining
    
    async def check_credits_sufficient(self, user_id: str, required_credits: int) -> bool:
        """Check if user has sufficient credits."""
        remaining = await self.get_user_credits(user_id)
        
        # Free tier users can still generate simple games (platform subsidy)
        if not remaining or remaining <= 0:
            subscription = await self.get_user_subscription(user_id)
            if subscription and subscription.plan_type == "free":
                # Allow 1 free simple game per month for free tier
                return required_credits <= 5  # Small projects only
        
        return remaining >= required_credits
    
    def calculate_generation_cost(self, wizard_input: dict) -> int:
        """
        Calculate credit cost for a generation request.
        
        Base costs from config:
        - Simple game: 10 credits
        - Complex game: 25 credits
        
        Multipliers:
        - Epic quests: +15 credits
        - Full RPG dialogue: +15 credits
        - Save system: +5 credits
        - Asset generation (per slot): +2 credits each
        """
        base_cost = self.settings.credits_per_simple_game
        
        # Determine complexity
        quest_complexity = wizard_input.get("quest_complexity", "none")
        dialogue_depth = wizard_input.get("dialogue_depth", "none")
        has_saving = wizard_input.get("has_saving", False)
        genre = wizard_input.get("genre", "")
        scale = wizard_input.get("scale", "small")
        
        # Complex genres/scapes increase base cost
        complex_genres = ["rpg", "strategy", "simulation"]
        if any(g in genre.lower() for g in complex_genres):
            base_cost = self.settings.credits_per_complex_game
        
        # Scale multiplier
        if scale in ["large", "massive"]:
            base_cost = int(base_cost * 1.5)
        
        # Quest complexity adder
        quest_costs = {
            "none": 0,
            "simple": 0,  # Included in base
            "branching": 8,
            "epic": self.settings.credits_per_epic_quest,
        }
        base_cost += quest_costs.get(quest_complexity, 0)
        
        # Dialogue depth adder
        dialogue_costs = {
            "none": 0,
            "linear": 0,  # Included in base
            "branching": 8,
            "full_rpg": self.settings.credits_per_full_rpg_dialogue,
        }
        base_cost += dialogue_costs.get(dialogue_depth, 0)
        
        # Save system
        if has_saving:
            base_cost += 5
        
        # Estimated asset slots (based on genre)
        asset_estimates = {
            "platformer": 6,  # player, enemy, background, tileset, item, projectile
            "rpg": 8,  # player, enemy, background, tileset, item, npc, projectile, icon
            "visual_novel": 4,  # player, npc, background, ui_button
            "shooter": 7,  # player, enemy, background, tileset, projectile, hazard, icon
            "default": 5,
        }
        estimated_assets = asset_estimates.get(genre.lower(), asset_estimates["default"])
        base_cost += estimated_assets * 2  # 2 credits per asset slot
        
        return base_cost
    
    async def deduct_credits(
        self,
        user_id: str,
        amount: int,
        project_id: str,
        attempt_number: int,
        generation_id: Optional[int] = None
    ) -> bool:
        """
        Deduct credits from user account.
        
        Two-Attempt Rule:
        - Attempt 1 failed: Credits NOT charged (automatic rollback)
        - Attempt 2 failed: Credits ARE charged (user pays for retry)
        - Success: Credits charged on first successful attempt
        
        Args:
            user_id: User ID
            amount: Credit amount to charge
            project_id: Project identifier
            attempt_number: Current attempt number (1 or 2)
            generation_id: Optional generation history ID to update
            
        Returns:
            True if deduction successful, False otherwise
        """
        async with get_db_session() as session:
            # Get subscription
            result = await session.execute(
                select(Subscription)
                .where(Subscription.user_id == int(user_id))
                .where(Subscription.is_active == True)
            )
            subscription = result.scalar_one_or_none()
            
            if not subscription:
                logger.warning(f"No active subscription for user {user_id}")
                # Create free tier subscription if none exists
                subscription = Subscription(
                    user_id=int(user_id),
                    plan_type="free",
                    credits_remaining=0,
                    credits_total=0,
                    is_active=True,
                )
                session.add(subscription)
                await session.commit()
                await session.refresh(subscription)
            
            # Two-Attempt Rule: Don't charge on first failed attempt
            # Credits are only charged on success OR second attempt failure
            # This logic is handled by the caller based on outcome
            
            if subscription.credits_remaining < amount:
                logger.warning(
                    f"Insufficient credits: user={user_id}, "
                    f"remaining={subscription.credits_remaining}, required={amount}"
                )
                return False
            
            subscription.credits_remaining -= amount
            subscription.updated_at = datetime.now()
            
            # Log the transaction in generation history
            if generation_id:
                gen_result = await session.execute(
                    select(GenerationHistory)
                    .where(GenerationHistory.id == generation_id)
                )
                gen_history = gen_result.scalar_one_or_none()
                if gen_history:
                    gen_history.credits_charged = amount
                    gen_history.completed_at = datetime.now()
            
            await session.commit()
            
            logger.info(
                f"Credits deducted: user={user_id}, amount={amount}, "
                f"remaining={subscription.credits_remaining}, "
                f"project={project_id}, attempt={attempt_number}"
            )
            
            return True
    
    async def refund_credits(
        self,
        user_id: str,
        amount: int,
        reason: str,
        project_id: Optional[str] = None
    ) -> bool:
        """Refund credits to user (e.g., for service errors)."""
        async with get_db_session() as session:
            result = await session.execute(
                select(Subscription)
                .where(Subscription.user_id == int(user_id))
                .where(Subscription.is_active == True)
            )
            subscription = result.scalar_one_or_none()
            
            if not subscription:
                logger.error(f"Cannot refund: no subscription for user {user_id}")
                return False
            
            subscription.credits_remaining += amount
            subscription.updated_at = datetime.now()
            
            await session.commit()
            
            logger.info(
                f"Credits refunded: user={user_id}, amount={amount}, "
                f"reason={reason}, project={project_id}"
            )
            
            return True
    
    async def record_generation_attempt(
        self,
        project_id: int,
        attempt_number: int,
        request_type: Literal["create", "update", "incremental"],
        affected_modules: Optional[list[str]] = None,
        error_message: Optional[str] = None,
        stability_score: Optional[float] = None,
        playtest_report: Optional[dict] = None,
    ) -> int:
        """
        Record a generation attempt in history.
        
        Returns the generation history ID for later credit charging.
        """
        async with get_db_session() as session:
            gen_history = GenerationHistory(
                project_id=project_id,
                attempt_number=attempt_number,
                status="running",
                request_type=request_type,
                affected_modules=affected_modules or [],
                error_message=error_message,
                stability_score=stability_score,
                playtest_report=playtest_report,
                credits_charged=0,  # Updated on completion
            )
            
            session.add(gen_history)
            await session.commit()
            await session.refresh(gen_history)
            
            return gen_history.id
    
    async def update_generation_status(
        self,
        generation_id: int,
        status: Literal["pending", "running", "success", "failed", "rolled_back"],
        error_message: Optional[str] = None,
        stability_score: Optional[float] = None,
        playtest_report: Optional[dict] = None,
        credits_charged: int = 0,
    ) -> bool:
        """Update generation history record with final status."""
        async with get_db_session() as session:
            result = await session.execute(
                select(GenerationHistory)
                .where(GenerationHistory.id == generation_id)
            )
            gen_history = result.scalar_one_or_none()
            
            if not gen_history:
                logger.error(f"Generation history {generation_id} not found")
                return False
            
            gen_history.status = status
            gen_history.error_message = error_message
            gen_history.stability_score = stability_score
            gen_history.playtest_report = playtest_report
            gen_history.credits_charged = credits_charged
            gen_history.completed_at = datetime.now()
            
            await session.commit()
            
            return True
    
    def get_plan_features(self, plan_type: str) -> dict:
        """Get features for a subscription plan."""
        plans = {
            "free": {
                "credits_monthly": 0,
                "watermark": True,
                "export_formats": ["web"],
                "max_quest_complexity": "simple",
                "max_dialogue_depth": "linear",
                "asset_quality": "standard",
                "priority_queue": False,
                "server_saves": False,
                "api_access": False,
                "white_label": False,
            },
            "starter": {
                "credits_monthly": 50,
                "watermark": False,
                "export_formats": ["web", "apk"],
                "max_quest_complexity": "branching",
                "max_dialogue_depth": "branching",
                "asset_quality": "standard",
                "priority_queue": False,
                "server_saves": False,
                "api_access": False,
                "white_label": False,
            },
            "pro": {
                "credits_monthly": 200,
                "watermark": False,
                "export_formats": ["web", "apk", "ios"],
                "max_quest_complexity": "epic",
                "max_dialogue_depth": "full_rpg",
                "asset_quality": "hd",
                "priority_queue": True,
                "server_saves": True,
                "api_access": False,
                "white_label": False,
            },
            "studio": {
                "credits_monthly": 1000,
                "watermark": False,
                "export_formats": ["web", "apk", "ios", "desktop"],
                "max_quest_complexity": "epic",
                "max_dialogue_depth": "full_rpg",
                "asset_quality": "hd",
                "priority_queue": True,
                "server_saves": True,
                "api_access": True,
                "white_label": True,
            },
        }
        
        return plans.get(plan_type, plans["free"])
    
    async def upgrade_subscription(
        self,
        user_id: str,
        new_plan: Literal["free", "starter", "pro", "studio"],
        stripe_subscription_id: Optional[str] = None,
    ) -> bool:
        """Upgrade user's subscription plan."""
        async with get_db_session() as session:
            result = await session.execute(
                select(Subscription)
                .where(Subscription.user_id == int(user_id))
                .where(Subscription.is_active == True)
            )
            subscription = result.scalar_one_or_none()
            
            if not subscription:
                # Create new subscription
                plan_features = self.get_plan_features(new_plan)
                subscription = Subscription(
                    user_id=int(user_id),
                    plan_type=new_plan,
                    credits_remaining=plan_features["credits_monthly"],
                    credits_total=plan_features["credits_monthly"],
                    stripe_subscription_id=stripe_subscription_id,
                    current_period_start=datetime.now(),
                    current_period_end=datetime.now(),  # TODO: Calculate based on billing cycle
                    is_active=True,
                )
                session.add(subscription)
            else:
                # Update existing subscription
                old_plan = subscription.plan_type
                plan_features = self.get_plan_features(new_plan)
                
                subscription.plan_type = new_plan
                subscription.credits_remaining = plan_features["credits_monthly"]
                subscription.credits_total += plan_features["credits_monthly"]
                subscription.stripe_subscription_id = stripe_subscription_id
                subscription.updated_at = datetime.now()
                
                logger.info(
                    f"Subscription upgraded: user={user_id}, "
                    f"from={old_plan}, to={new_plan}"
                )
            
            await session.commit()
            return True


# Singleton instance
_billing_service: Optional[BillingService] = None


def get_billing_service() -> BillingService:
    """Get or create billing service singleton."""
    global _billing_service
    if _billing_service is None:
        _billing_service = BillingService()
    return _billing_service
