from fastapi import APIRouter
from . import presence, pose, vitals, nodes, system, led, ir

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(presence.router, tags=["presence"])
v1_router.include_router(pose.router,     tags=["pose"])
v1_router.include_router(vitals.router,   tags=["vitals"])
v1_router.include_router(nodes.router,    tags=["nodes"])
v1_router.include_router(system.router,   tags=["system"])
v1_router.include_router(led.router,      tags=["led"])
v1_router.include_router(ir.router,       tags=["ir"])
