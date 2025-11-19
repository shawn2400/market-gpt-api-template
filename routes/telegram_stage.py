# routes/telegram_stage.py
"""
🎯 Telegram Stage Commands
/stage_status - Show current stage and health
/stage_promote - Manual promote to next stage  
/stage_freeze - Freeze system (disable auto-trading)
/stage_unfreeze - Unfreeze system (resume auto-promotion)
/stage_logs - Show last 20 log lines
"""
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from utils import stage_engine, stage_controller
from utils.telegram_notifier import notify_info, notify_error

logger = logging.getLogger("algogpt.telegram_stage")

router = APIRouter()


@router.post("/telegram/stage/status")
async def telegram_stage_status(request: Request):
    """Handle /stage_status command"""
    try:
        # Get comprehensive status
        # FIX: get_stage_summary() is now async
        summary = await stage_controller.get_stage_summary()
        status = stage_engine.get_stage_status()
        
        # Build response message
        frozen_emoji = "🥶" if status["frozen"] else "✅"
        health_emoji = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "❌"}.get(summary["health"], "❓")
        
        message = (
            f"📊 **AlgoGPT Stage Status**\n\n"
            f"**Stage {status['stage']}: {status['stage_name']}**\n"
            f"{status['stage_description']}\n\n"
            f"Status: {frozen_emoji} {'FROZEN' if status['frozen'] else 'Active'}\n"
            f"Uptime: {status['uptime_hours']:.1f}h ({status['uptime_minutes']:.0f}m)\n"
            f"Health: {health_emoji} {summary['health']}\n\n"
            f"**Metrics:**\n"
            f"• CPU: {summary['metrics'].get('cpu', 0):.1f}%\n"
            f"• RAM: {summary['metrics'].get('ram', 0):.1f}%\n"
            f"• Redis: {summary['metrics'].get('redis', 'unknown')}\n"
            f"• BanShield: {summary['metrics'].get('ban_shield_zone', 'unknown')}\n"
            f"• WS: {summary['metrics'].get('ws', 'n/a')}\n"
            f"• Errors (10m): {summary['metrics'].get('errors_10m', 0)}\n"
        )
        
        if status["frozen"]:
            message += f"\n🥶 **Freeze Reason:**\n{status['freeze_reason']}\n"
        
        if summary["issues"]:
            message += f"\n⚠️ **Issues:**\n"
            for issue in summary["issues"]:
                message += f"  • {issue}\n"
        
        if status["can_promote"]:
            message += f"\n✅ Can promote to Stage {status['stage'] + 1}\n"
        
        await notify_info(message)
        
        return JSONResponse({
            "status": "ok",
            "message": "Stage status sent to Telegram"
        })
        
    except Exception as e:
        logger.error(f"Failed to get stage status: {e}", exc_info=True)
        await notify_error(f"Failed to get stage status: {e}")
        return JSONResponse({
            "status": "error",
            "error": str(e)
        }, status_code=500)


@router.post("/telegram/stage/promote")
async def telegram_stage_promote(request: Request):
    """Handle /stage_promote command (manual promotion)"""
    try:
        current_stage = stage_engine.get_current_stage()
        
        if current_stage >= 3:
            await notify_info("Already at maximum stage (3)")
            return JSONResponse({
                "status": "ok",
                "message": "Already at max stage"
            })
        
        if stage_engine.is_frozen():
            freeze_reason = stage_engine.get_freeze_reason()
            await notify_error(
                f"Cannot promote while frozen!\n"
                f"Reason: {freeze_reason}\n\n"
                f"Use /stage_unfreeze first"
            )
            return JSONResponse({
                "status": "error",
                "error": "System is frozen"
            }, status_code=400)
        
        # Attempt promotion
        success = stage_engine.promote_stage()
        
        if success:
            new_status = stage_engine.get_stage_status()
            await notify_info(
                f"✅ Manual promotion successful!\n\n"
                f"Stage {current_stage} → Stage {new_status['stage']}\n"
                f"**{new_status['stage_name']}**\n"
                f"{new_status['stage_description']}"
            )
            return JSONResponse({
                "status": "ok",
                "message": f"Promoted to stage {new_status['stage']}"
            })
        else:
            await notify_error("Failed to promote stage")
            return JSONResponse({
                "status": "error",
                "error": "Promotion failed"
            }, status_code=500)
        
    except Exception as e:
        logger.error(f"Failed to promote stage: {e}", exc_info=True)
        await notify_error(f"Failed to promote stage: {e}")
        return JSONResponse({
            "status": "error",
            "error": str(e)
        }, status_code=500)


@router.post("/telegram/stage/freeze")
async def telegram_stage_freeze(request: Request):
    """Handle /stage_freeze command"""
    try:
        data = await request.json()
        reason = data.get("reason", "Manual freeze via Telegram")
        
        if stage_engine.is_frozen():
            current_reason = stage_engine.get_freeze_reason()
            await notify_info(
                f"System already frozen!\n"
                f"Current reason: {current_reason}"
            )
            return JSONResponse({
                "status": "ok",
                "message": "Already frozen"
            })
        
        # Freeze system
        success = stage_engine.freeze_stage(reason)
        
        if success:
            await notify_info(
                f"🥶 System FROZEN\n\n"
                f"Reason: {reason}\n"
                f"Stage: {stage_engine.get_current_stage()}\n\n"
                f"Auto-promotion disabled\n"
                f"Auto-trading disabled\n\n"
                f"Use /stage_unfreeze to resume"
            )
            return JSONResponse({
                "status": "ok",
                "message": "System frozen"
            })
        else:
            await notify_error("Failed to freeze system")
            return JSONResponse({
                "status": "error",
                "error": "Freeze failed"
            }, status_code=500)
        
    except Exception as e:
        logger.error(f"Failed to freeze stage: {e}", exc_info=True)
        await notify_error(f"Failed to freeze stage: {e}")
        return JSONResponse({
            "status": "error",
            "error": str(e)
        }, status_code=500)


@router.post("/telegram/stage/unfreeze")
async def telegram_stage_unfreeze(request: Request):
    """Handle /stage_unfreeze command"""
    try:
        if not stage_engine.is_frozen():
            await notify_info("System is not frozen")
            return JSONResponse({
                "status": "ok",
                "message": "Not frozen"
            })
        
        old_reason = stage_engine.get_freeze_reason()
        
        # Unfreeze system
        success = stage_engine.unfreeze_stage()
        
        if success:
            status = stage_engine.get_stage_status()
            await notify_info(
                f"🌞 System UNFROZEN\n\n"
                f"Previous reason: {old_reason}\n"
                f"Stage: {status['stage']} ({status['stage_name']})\n\n"
                f"Auto-promotion resumed\n"
                f"System monitoring active"
            )
            return JSONResponse({
                "status": "ok",
                "message": "System unfrozen"
            })
        else:
            await notify_error("Failed to unfreeze system")
            return JSONResponse({
                "status": "error",
                "error": "Unfreeze failed"
            }, status_code=500)
        
    except Exception as e:
        logger.error(f"Failed to unfreeze stage: {e}", exc_info=True)
        await notify_error(f"Failed to unfreeze stage: {e}")
        return JSONResponse({
            "status": "error",
            "error": str(e)
        }, status_code=500)


@router.post("/telegram/stage/logs")
async def telegram_stage_logs(request: Request):
    """Handle /stage_logs command - show last 20 log lines"""
    try:
        import subprocess
        
        # Get last 20 lines from stage history
        try:
            with open("/tmp/algogpt_stage_history.txt", "r") as f:
                lines = f.readlines()
                recent_lines = lines[-20:] if len(lines) > 20 else lines
                
                if recent_lines:
                    log_text = "📜 **Stage History (last 20 events):**\n\n```\n"
                    log_text += "".join(recent_lines)
                    log_text += "```"
                else:
                    log_text = "📜 No stage history available"
        except FileNotFoundError:
            log_text = "📜 No stage history file found"
        
        await notify_info(log_text)
        
        return JSONResponse({
            "status": "ok",
            "message": "Stage logs sent to Telegram"
        })
        
    except Exception as e:
        logger.error(f"Failed to get stage logs: {e}", exc_info=True)
        await notify_error(f"Failed to get stage logs: {e}")
        return JSONResponse({
            "status": "error",
            "error": str(e)
        }, status_code=500)
