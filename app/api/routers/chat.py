import logging
import os
import json
import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from llama_index.core.llms import MessageRole
from dotenv import load_dotenv

from app.api.routers.events import EventCallbackHandler
from app.api.routers.models import (
    Annotation,
    AgentAnnotation,
    ChatData,
    Message,
    Result,
    SourceNodes,
)
from app.api.routers.vercel_response import VercelStreamResponse
from app.engine.engine import get_chat_engine
from app.engine.query_filter import generate_filters

chat_router = r = APIRouter()

logger = logging.getLogger("uvicorn")

load_dotenv()

def fetch_entities():
    url = os.getenv('API_URL')
    if not url:
        raise ValueError("API_URL is not set in the environment variables")
    token = os.getenv('TOKEN')
    if not token:
        raise ValueError("TOKEN is not set in the environment variables")

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    response = requests.get(url, headers=headers, verify=False)
    response.raise_for_status()
    return response.json()

def load_entity_descriptions(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)

def combine_entities_with_descriptions(entities, descriptions):
    description_dict = {desc["entity_id"]: desc["entity_description"] for desc in descriptions}
    combined = []
    for entity in entities:
        entity_id = entity["entity_id"]
        if entity_id in description_dict:
            combined_entity = entity.copy()
            combined_entity["entity_description"] = description_dict[entity_id]
            combined.append(combined_entity)
    return combined

def process_ha_rest_entities(data: ChatData):
    # Convertir la variable de entorno USE_API a un booleano
    use_api = os.getenv('USE_API', 'false').lower() in ('true', '1', 't', 'y', 'yes')
    if use_api:
        # Obtener las entidades desde la llamada al API REST a Home Assistant
        entidades = fetch_entities()        

        # Cargar las descripciones de las entidades desde el archivo JSON
        entidades_descripcion = load_entity_descriptions('entities.json')      

        # Combinar las entidades con sus descripciones, eliminando las que no tengan descripción
        entidades_combinadas = combine_entities_with_descriptions(entidades, entidades_descripcion)

        # Añadir la anotación de tipo agent con el contenido de las entidades combinadas
        agent_annotation = Annotation(
            type="agent",
            data=AgentAnnotation(
                agent="agent",
                text=str(entidades_combinadas)
            )
        )

        # Añadir la anotación al último mensaje del usuario
        if data.messages and data.messages[-1].role == MessageRole.USER:
            if data.messages[-1].annotations is None:
                data.messages[-1].annotations = []
            data.messages[-1].annotations.append(agent_annotation)

# streaming endpoint - delete if not needed
@r.post("")
async def chat(
    request: Request,
    data: ChatData,
    background_tasks: BackgroundTasks,
):
    try:        
        process_ha_rest_entities(data)

        last_message_content = data.get_last_message_content()
        messages = data.get_history_messages()

        doc_ids = data.get_chat_document_ids()
        filters = generate_filters(doc_ids)
        params = data.data or {}
        logger.info(
            f"Creating chat engine with filters: {str(filters)}",
        )
        event_handler = EventCallbackHandler()
        chat_engine = get_chat_engine(
            filters=filters, params=params, event_handlers=[event_handler]
        )
        response = chat_engine.astream_chat(last_message_content, messages)

        return VercelStreamResponse(
            request, event_handler, response, data, background_tasks
        )
    except Exception as e:
        logger.exception("Error in chat engine", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error in chat engine: {e}",
        ) from e

# non-streaming endpoint - delete if not needed
@r.post("/request")
async def chat_request(
    data: ChatData,
) -> Result:
    
    process_ha_rest_entities(data)

    last_message_content = data.get_last_message_content()
    messages = data.get_history_messages()

    doc_ids = data.get_chat_document_ids()
    filters = generate_filters(doc_ids)
    params = data.data or {}
    logger.info(
        f"Creating chat engine with filters: {str(filters)}",
    )

    chat_engine = get_chat_engine(filters=filters, params=params)

    response = await chat_engine.achat(last_message_content, messages)
    return Result(
        result=Message(role=MessageRole.ASSISTANT, content=response.response),
        nodes=SourceNodes.from_source_nodes(response.source_nodes),
    )
