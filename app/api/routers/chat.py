import logging
import os
import json
import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from llama_index.core.llms import MessageRole
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
import pandas as pd
from pandas import DataFrame

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

def fetch_ha_entities():
    url = os.getenv('HA_API_URL')
    if not url:
        raise ValueError("API_URL is not set in the environment variables")
    token = os.getenv('HA_TOKEN')
    if not token:
        raise ValueError("HA_TOKEN is not set in the environment variables")

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    response = requests.get(url, headers=headers, verify=False)
    response.raise_for_status()
    return response.json()

def load_ha_entity_descriptions(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)

def combine_ha_entities_with_descriptions(entities, descriptions):
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
    use_api = os.getenv('USE_HA_API', 'false').lower() in ('true', '1', 't', 'y', 'yes')
    if use_api:
        # Obtener las entidades desde la llamada al API REST a Home Assistant
        entidades = fetch_ha_entities()        

        # Cargar las descripciones de las entidades desde el archivo JSON
        entidades_descripcion = load_ha_entity_descriptions('ha-entities.json')      

        # Combinar las entidades con sus descripciones, eliminando las que no tengan descripción
        entidades_combinadas = combine_ha_entities_with_descriptions(entidades, entidades_descripcion)

        agent_description = os.getenv('HA_AGENT_DESCRIPTION', 'agent')

        # Añadir la anotación de tipo agent con el contenido de las entidades combinadas
        agent_annotation = Annotation(
            type="agent",
            data=AgentAnnotation(
                agent=agent_description,
                text=str(entidades_combinadas)
            )
        )

        # Añadir la anotación al último mensaje del usuario
        if data.messages and data.messages[-1].role == MessageRole.USER:
            if data.messages[-1].annotations is None:
                data.messages[-1].annotations = []
            data.messages[-1].annotations.append(agent_annotation)

def fetch_influxdb_data(bucket: str, org: str, query: str):
    url = os.getenv('IDB_API_URL')
    if not url:
        raise ValueError("IDB_API_URL is not set in the environment variables")
    token = os.getenv('IDB_TOKEN')
    if not token:
        raise ValueError("IDB_TOKEN is not set in the environment variables")
    client = InfluxDBClient(url=url, token=token, org=org, verify_ssl=False)
    query_api = client.query_api()
    data_frame = query_api.query_data_frame(query)    

    if isinstance(data_frame, DataFrame):
            return data_frame.to_json(orient="records")
    else:
        return ''

def process_influxdb_entities(data):
    # Procesar la primera consulta a InfluxDB
    use_idb_api_1 = os.getenv('USE_IDB_API_1', 'false').lower() in ('true', '1', 't', 'y', 'yes')
    if use_idb_api_1:
        bucket_1 = os.getenv('IDB_BUCKET_1')
        if not bucket_1:
            raise ValueError("IDB_BUCKET_1 is not set in the environment variables")
        org_1 = os.getenv('IDB_ORG_1')
        if not org_1:
            raise ValueError("IDB_ORG_1 is not set in the environment variables")
        query_1 = os.getenv('IDB_QUERY_1')
        if not query_1:
            raise ValueError("IDB_QUERY_1 is not set in the environment variables")
        agent_description_1 = os.getenv('IDB_AGENT_DESCRIPTION_1', 'agent')

        entities_1 = fetch_influxdb_data(bucket_1, org_1, query_1)
        agent_annotation_1 = Annotation(
            type="agent",
            data=AgentAnnotation(
                agent=agent_description_1,
                text=entities_1
            )
        )

        if data.messages and data.messages[-1].role == MessageRole.USER:
            if data.messages[-1].annotations is None:
                data.messages[-1].annotations = []
            data.messages[-1].annotations.append(agent_annotation_1)

    # Procesar la segunda consulta a InfluxDB
    use_idb_api_2 = os.getenv('USE_IDB_API_2', 'false').lower() in ('true', '1', 't', 'y', 'yes')
    if use_idb_api_2:
        bucket_2 = os.getenv('IDB_BUCKET_2')
        if not bucket_2:
            raise ValueError("IDB_BUCKET_2 is not set in the environment variables")
        org_2 = os.getenv('IDB_ORG_2')
        if not org_2:
            raise ValueError("IDB_ORG_2 is not set in the environment variables")
        query_2 = os.getenv('IDB_QUERY_2')
        if not query_2:
            raise ValueError("IDB_QUERY_2 is not set in the environment variables")
        agent_description_2 = os.getenv('IDB_AGENT_DESCRIPTION_2', 'agent')

        entities_2 = fetch_influxdb_data(bucket_2, org_2, query_2)
        agent_annotation_2 = Annotation(
            type="agent",
            data=AgentAnnotation(
                agent=agent_description_2,
                text=entities_2
            )
        )

        if data.messages and data.messages[-1].role == MessageRole.USER:
            if data.messages[-1].annotations is None:
                data.messages[-1].annotations = []
            data.messages[-1].annotations.append(agent_annotation_2)

# streaming endpoint - delete if not needed
@r.post("")
async def chat(
    request: Request,
    data: ChatData,
    background_tasks: BackgroundTasks,
):
    try:        
        process_ha_rest_entities(data)
        process_influxdb_entities(data)

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
    process_influxdb_entities(data)

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
