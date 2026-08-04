from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.gemini_engine import ask_gemini, gemini_enabled
from app.services.ml_engine import (
    group_anomaly_events,
    isolation_forest_anomalies,
    kmeans_building_clusters,
    random_forest_forecast,
)
from app.services.model_confidence import real_forecast_confidence

router = APIRouter()


class AssistantQuestion(BaseModel):
    question: str


@router.get("")
def ai_center(db: Session = Depends(get_db)):
    forecast = random_forest_forecast(db)
    confidence_info = real_forecast_confidence(db)
    forecast["confidence"] = confidence_info["confidence"]
    forecast["confidence_method"] = confidence_info["method"]
    forecast["confidence_samples"] = confidence_info["samples"]
    forecast["confidence_mape"] = confidence_info["mape"]
    anomaly_result = isolation_forest_anomalies(db)
    cluster_result = kmeans_building_clusters(db)

    raw_anomalies = anomaly_result.get("items", [])
    grouped_anomalies = group_anomaly_events(raw_anomalies)

    return {
        "models": {
            "forecast": forecast["model"],
            "forecast_trained": forecast["trained"],
            "anomaly_detection": anomaly_result["model"],
            "anomaly_trained": anomaly_result["trained"],
            "clustering": cluster_result["model"],
            "clustering_trained": cluster_result["trained"],
        },
        "forecast": {
            "tomorrow_mxn": forecast["tomorrow_mxn"],
            "week_mxn": forecast["week_mxn"],
            "month_mxn": forecast["month_mxn"],
            "confidence": forecast.get("confidence"),
            "confidence_method": forecast.get("confidence_method"),
            "confidence_samples": forecast.get("confidence_samples"),
            "confidence_mape": forecast.get("confidence_mape"),
            "points": forecast["points"],
            "method": forecast["reason"],
            "model": forecast["model"],
        },
        "anomalies": {
            "today_count": len(grouped_anomalies),
            "week_count": len(grouped_anomalies),
            "raw_count": len(raw_anomalies),
            "reviewed": 0,
            "items": grouped_anomalies,
            "model": anomaly_result["model"],
            "trained": anomaly_result["trained"],
            "reason": anomaly_result["reason"],
        },
        "recommendations": [
            {
                "priority": "Alta prioridad",
                "title": "Revisar anomalías detectadas por IA",
                "building": item.get("building", "Sistema"),
                "description": item.get(
                    "description", "Anomalía agrupada detectada por el modelo."
                ),
                "action": "Revisar tablero, carga conectada y factor de potencia.",
                "saving_mxn_month": round(forecast["month_mxn"] * 0.05, 2),
            }
            for item in grouped_anomalies[:3]
        ]
        + [
            {
                "priority": "Prioridad media",
                "title": "Optimizar consumo en horarios punta",
                "building": "Sistema",
                "description": "Con base en la proyección Random Forest, desplazar cargas no críticas puede reducir el costo mensual.",
                "action": "Programar cargas fuera de horario punta.",
                "saving_mxn_month": round(forecast["month_mxn"] * 0.08, 2),
            }
        ],
        "clusters": cluster_result["clusters"],
    }


@router.post("/assistant")
def ai_assistant(payload: AssistantQuestion, db: Session = Depends(get_db)):
    forecast = random_forest_forecast(db)
    confidence_info = real_forecast_confidence(db)
    forecast["confidence"] = confidence_info["confidence"]
    forecast["confidence_method"] = confidence_info["method"]
    forecast["confidence_samples"] = confidence_info["samples"]
    forecast["confidence_mape"] = confidence_info["mape"]
    anomaly_result = isolation_forest_anomalies(db)
    cluster_result = kmeans_building_clusters(db)

    raw_anomalies = anomaly_result.get("items", [])
    grouped_anomalies = group_anomaly_events(raw_anomalies)

    context = {
        "models": {
            "forecast": forecast["model"],
            "forecast_trained": forecast["trained"],
            "anomaly_detection": anomaly_result["model"],
            "anomaly_trained": anomaly_result["trained"],
            "clustering": cluster_result["model"],
            "clustering_trained": cluster_result["trained"],
        },
        "forecast": forecast,
        "anomalies": {
            "model": anomaly_result["model"],
            "trained": anomaly_result["trained"],
            "raw_count": len(raw_anomalies),
            "grouped_count": len(grouped_anomalies),
            "items": grouped_anomalies,
        },
        "clusters": cluster_result,
        "note": "Las anomalías están agrupadas por tipo y edificio para evitar repeticiones por cada lectura.",
    }

    if gemini_enabled():
        try:
            answer = ask_gemini(payload.question, context)
            if answer:
                return {
                    "answer": answer,
                    "model": "gemini",
                    "provider": "Google AI Studio",
                }
        except Exception as e:
            return {
                "answer": f"Gemini no respondió correctamente: {e!s}. El backend ML local sigue funcionando.",
                "model": "fallback",
                "provider": "local",
            }

    return {
        "answer": "Gemini no está habilitado. El backend ML local está disponible, pero el chat natural requiere GEMINI_API_KEY.",
        "model": "fallback",
        "provider": "local",
    }
