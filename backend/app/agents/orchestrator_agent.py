from typing import Dict, Any, List, Optional, TypedDict, Annotated
from datetime import datetime, timedelta
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
import asyncio
import logging
import operator
import uuid

from app.agents.base_agent import AgentType, AgentStatus, StreamingUpdateType
from app.messaging.redis_client import RedisClient, RedisChannels, get_redis_client
from app.config.settings import settings


# ==================== STATE DEFINITION ====================

class OrchestratorState(TypedDict):
    """State for the orchestrator workflow"""
    # Session info
    session_id: str
    user_query: str
    is_follow_up: bool  # NEW: Track if this is a follow-up query
    conversation_history: List[Dict[str, str]]  # NEW: Chat history
    
    # Travel parameters
    destination: Optional[str]
    origin: Optional[str]
    travel_dates: List[str]
    travelers_count: int
    budget_range: Optional[str]
    user_preferences: Optional[Dict[str, Any]]
    needs_itinerary: bool

    query_type: str
    update_type: Optional[str]  # NEW: "budget_update", "itinerary_update", "dates_update", etc.
    

    # Workflow control
    agents_to_execute: List[str]
    agent_statuses: Dict[str, str]
    agent_responses: Dict[str, Any]
    
    # Results
    weather_data: Optional[Dict[str, Any]]
    events_data: Optional[Dict[str, Any]]
    maps_data: Optional[Dict[str, Any]]
    budget_data: Optional[Dict[str, Any]]
    itinerary_data: Optional[Dict[str, Any]]
    
    # Metadata
    messages: Annotated[List[str], operator.add]
    errors: Annotated[List[str], operator.add]
    workflow_status: str
    start_time: str
    end_time: Optional[str]


# ==================== ORCHESTRATOR AGENT WITH MEMORY ====================

class OrchestratorAgent:
    """
    Enhanced Orchestrator Agent with Memory Management
    
    New Features:
    - Session-based memory storage and retrieval
    - Conversation history tracking
    - Context-aware follow-up query handling
    - Incremental updates (budget changes, itinerary modifications)
    - Smart agent selection based on conversation context
    """
    
    def __init__(
        self,
        redis_client: Optional[RedisClient] = None,
        gemini_api_key: str = None,
        model_name: str = "gemini-2.5-flash"
    ):
        self.redis_client = redis_client or get_redis_client()
        self.logger = logging.getLogger("orchestrator")
        
        # Initialize Gemini LLM
        api_key = gemini_api_key or getattr(settings, 'google_api_key', None)
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0.3,
            max_output_tokens=4096
        )
        
        # Build LangGraph workflow
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Build the orchestrator workflow graph with memory support"""
        workflow = StateGraph(OrchestratorState)
        
        # Add nodes
        workflow.add_node("load_memory", self._load_memory_node)  # NEW
        workflow.add_node("classify_query", self._classify_query_node)  # NEW
        workflow.add_node("parse_query", self._parse_query_node)
        workflow.add_node("validate_params", self._validate_params_node)
        workflow.add_node("dispatch_agents", self._dispatch_agents_node)
        workflow.add_node("collect_responses", self._collect_responses_node)
        workflow.add_node("synthesize_plan", self._synthesize_plan_node)
        workflow.add_node("finalize", self._finalize_node)
        
        # Define edges
        workflow.set_entry_point("load_memory")
        workflow.add_edge("load_memory", "classify_query")
        
        # Conditional edge after classification
        workflow.add_conditional_edges(
            "classify_query",
            self._route_after_classification,
            {
                "parse": "parse_query",
                "validate": "validate_params",  # NEW: Skip parsing for simple updates
                "end": "finalize"
            }
        )
        
        workflow.add_edge("parse_query", "validate_params")
        
        # Conditional edge after validation
        workflow.add_conditional_edges(
            "validate_params",
            self._should_continue_after_validation,
            {
                "dispatch": "dispatch_agents",
                "end": "finalize"
            }
        )
        
        workflow.add_edge("dispatch_agents", "collect_responses")
        workflow.add_edge("collect_responses", "synthesize_plan")
        workflow.add_edge("synthesize_plan", "finalize")
        workflow.add_edge("finalize", END)
        
        return workflow.compile()
    
    # ==================== NEW MEMORY NODES ====================
    
    async def _load_memory_node(self, state: OrchestratorState) -> OrchestratorState:
        """Load previous session state from Redis if it exists"""
        session_id = state["session_id"]
        self.logger.info(f"🧠 Loading memory for session {session_id}")
        
        # Try to load previous state
        previous_state = await self.redis_client.get_state(session_id)
        
        if previous_state:
            self.logger.info(f"✅ Found existing session memory")
            state["is_follow_up"] = True
            
            # Restore key fields from previous state
            state["destination"] = previous_state.get("destination")
            state["origin"] = previous_state.get("origin")
            state["travel_dates"] = previous_state.get("travel_dates", [])
            state["travelers_count"] = previous_state.get("travelers_count")
            state["budget_range"] = previous_state.get("budget_range")
            state["user_preferences"] = previous_state.get("user_preferences")
            
            # Restore previous agent data
            state["weather_data"] = previous_state.get("weather_data")
            state["events_data"] = previous_state.get("events_data")
            state["maps_data"] = previous_state.get("maps_data")
            state["budget_data"] = previous_state.get("budget_data")
            state["itinerary_data"] = previous_state.get("itinerary_data")
            
            # Load conversation history
            state["conversation_history"] = previous_state.get("conversation_history", [])
            
            # Add current query to history
            state["conversation_history"].append({
                "role": "user",
                "content": state["user_query"],
                "timestamp": datetime.utcnow().isoformat()
            })
            
            self.logger.info(
                f"📚 Restored context: destination={state['destination']}, "
                f"dates={state['travel_dates']}, history={len(state['conversation_history'])} messages"
            )
            
            await self._send_streaming_update(
                session_id=session_id,
                agent="orchestrator",
                message=f"Continuing conversation (loaded previous context)",
                update_type="progress",
                progress_percent=5
            )
        else:
            self.logger.info(f"🆕 New session - no previous memory")
            state["is_follow_up"] = False
            state["conversation_history"] = [{
                "role": "user",
                "content": state["user_query"],
                "timestamp": datetime.utcnow().isoformat()
            }]
        
        return state
    
    async def _classify_query_node(self, state: OrchestratorState) -> OrchestratorState:
        """Classify the query type and determine if it's an update request"""
        self.logger.info("🔍 Classifying query intent")
        
        user_query = state["user_query"].lower()
        is_follow_up = state["is_follow_up"]
        
        # Build context string from previous state
        context_summary = ""
        if is_follow_up:
            context_summary = f"""
Previous Context:
- Destination: {state.get('destination', 'Not set')}
- Travel Dates: {state.get('travel_dates', 'Not set')}
- Budget: {state.get('budget_range', 'Not set')}
- Travelers: {state.get('travelers_count', 'Not set')}
- Has Itinerary: {'Yes' if state.get('itinerary_data') else 'No'}
- Has Budget Data: {'Yes' if state.get('budget_data') else 'No'}
"""
            self.logger.info(f"📚 Loaded context: {context_summary.strip()}")
        
        system_prompt = f"""
You are a travel query classifier. Analyze the user's query and determine the intent.

{context_summary}

Current Query: "{state['user_query']}"

Classify the query as ONE of:
1. "new_query" - A completely new travel planning request
2. "budget_update" - Request to change/update budget (keywords: "change budget", "update budget", "different budget", "cheaper", "more expensive", "increase", "decrease")
3. "itinerary_update" - Request to modify existing itinerary (keywords: "change itinerary", "update plan", "add activity", "remove", "modify")
4. "dates_update" - Request to change travel dates
5. "destination_update" - Request to change destination
6. "simple_question" - Simple question about existing plan (keywords: "what about", "tell me about", "show me")
7. "refinement" - Refining preferences or adding details to existing plan

IMPORTANT RULES:
- If NO previous context exists (first message), ALWAYS classify as "new_query"
- If previous context exists:
  * Look for update/change keywords
  * Consider if query references existing plan
  * "change X", "update X", "different X", "increase X", "decrease X" → likely an update
  * Questions about existing data → "simple_question"

Return EXACTLY in this format:
Classification: <classification>
Update Type: <specific_update_type or "none">
Reasoning: <brief explanation>
"""
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Classify: {state['user_query']}")
            ])
            
            # Parse classification
            lines = response.content.strip().split('\n')
            classification = "new_query"
            update_type = None
            reasoning = ""
            
            for line in lines:
                if "classification:" in line.lower():
                    classification = line.split(':', 1)[1].strip().lower().replace(" ", "_")
                elif "update type:" in line.lower():
                    update_val = line.split(':', 1)[1].strip().lower()
                    if update_val != "none":
                        update_type = update_val
                elif "reasoning:" in line.lower():
                    reasoning = line.split(':', 1)[1].strip()
            
            state["update_type"] = update_type
            
            self.logger.info(f"🎯 Classification: {classification} | Update: {update_type} | Reason: {reasoning}")
            
            # Determine query type based on classification
            if not is_follow_up or classification == "new_query":
                state["query_type"] = "multi_aspect"
                self.logger.info("📝 New query detected - full parsing needed")
            elif classification == "budget_update":
                state["query_type"] = "budget_only"
                state["agents_to_execute"] = ["budget"]
                self.logger.info("💰 Budget update detected - will use existing context")
            elif classification == "itinerary_update":
                state["query_type"] = "full_itinerary"
                state["needs_itinerary"] = True
                # Re-run itinerary agent with modification request
                state["agents_to_execute"] = ["itinerary"]
                self.logger.info("📋 Itinerary modification detected")
            elif classification == "dates_update":
                # Need to re-fetch weather and potentially regenerate itinerary
                state["query_type"] = "multi_aspect"
                self.logger.info("📅 Dates update detected - will re-fetch relevant data")
            elif classification == "simple_question":
                state["query_type"] = "simple_question"
                self.logger.info("❓ Simple question - may not need new data")
            else:
                state["query_type"] = "multi_aspect"
                self.logger.info("🔄 Query refinement detected")
            
            state["messages"].append(f"Query classified as: {classification}")
            
        except Exception as e:
            self.logger.error(f"Classification failed: {str(e)}")
            state["query_type"] = "multi_aspect"
            state["update_type"] = None
        
        return state
    
    def _route_after_classification(self, state: OrchestratorState) -> str:
        """Route workflow based on query classification"""
        query_type = state.get("query_type", "multi_aspect")
        is_follow_up = state.get("is_follow_up", False)
        update_type = state.get("update_type")
        
        # If it's a simple question about existing data, no need to fetch new data
        if query_type == "simple_question" and is_follow_up:
            return "end"
        
        # If it's a specific update and we already have context, skip parsing
        if is_follow_up and update_type in ["budget_update", "itinerary_update"]:
            # Skip parsing, go directly to validation and then dispatch
            self.logger.info(f"⚡ Fast path: {update_type} detected - skipping parse, going to validation")
            return "validate"
        
        # If dates are changing, need to parse the new dates
        if is_follow_up and update_type == "dates_update":
            return "parse"
        
        # If destination is not set or it's a new query, need full parsing
        if not state.get("destination") or query_type == "multi_aspect":
            return "parse"
        
        # For other follow-ups with context, go to validation
        if is_follow_up and state.get("destination"):
            return "validate"
        
        return "parse"
    
    # ==================== ENHANCED WORKFLOW NODES ====================
    
    async def _parse_query_node(self, state: OrchestratorState) -> OrchestratorState:
        """Parse user query with conversation context"""
        self.logger.info(f"🔍 Parsing user query for session {state['session_id']}")
        
        await self._send_streaming_update(
            session_id=state["session_id"],
            agent="orchestrator",
            message="Analyzing your travel request...",
            update_type="progress",
            progress_percent=10
        )
        
        user_query = state["user_query"]
        is_follow_up = state["is_follow_up"]
        
        # Get current date
        from datetime import date
        today_date = date.today().strftime("%Y-%m-%d")
        
        # Build conversation context for LLM
        context_str = ""
        if is_follow_up and state.get("conversation_history"):
            recent_history = state["conversation_history"][-5:]  # Last 5 messages
            context_str = "Previous conversation:\n"
            for msg in recent_history[:-1]:  # Exclude current message
                context_str += f"{msg['role']}: {msg['content']}\n"
        
        system_prompt = f"""
You are a travel query parser. Extract structured information from user travel queries.

IMPORTANT: Today's date is {today_date}.

{context_str}

Current State (if available):
- Destination: {state.get('destination', 'Not set')}
- Origin: {state.get('origin', 'Not set')}
- Travel Dates: {state.get('travel_dates', 'Not set')}
- Travelers Count: {state.get('travelers_count', 'Not set')}
- Budget Range: {state.get('budget_range', 'Not set')}

Extract from the NEW query (fill in missing fields or UPDATE existing ones):
- destination
- origin
- travel_dates (YYYY-MM-DD format)
- travelers_count (default 1)
- budget_range
- interests
- query_type: "weather_only", "events_only", "maps_only", "budget_only", "full_itinerary", "multi_aspect"

If the user is updating/changing a field, extract the NEW value.
If a field is not mentioned, keep the existing value (use "Keep existing" in response).

Return EXACTLY in this format:
Destination: <destination or "Keep existing">
Origin: <origin or "Keep existing">
Travel Dates: <dates or "Keep existing">
Travelers Count: <number or "Keep existing" or 1>
Budget Range: <budget or "Keep existing">
Interests: <interests or "Keep existing">
Query Type: <query_type>
"""
        
        user_input = f"Parse this travel query: {user_query}"
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_input)
            ])
            
            parsed_data = self._parse_llm_extraction(response.content)
            
            # Update state only with new values (don't override with "Keep existing")
            if parsed_data.get("destination") and parsed_data["destination"] != "keep_existing":
                state["destination"] = parsed_data["destination"]
            
            if parsed_data.get("origin") and parsed_data["origin"] != "keep_existing":
                state["origin"] = parsed_data["origin"]
            
            if parsed_data.get("travel_dates") and parsed_data["travel_dates"] != ["keep_existing"]:
                state["travel_dates"] = parsed_data["travel_dates"]
            
            if parsed_data.get("travelers_count") and parsed_data["travelers_count"] != "keep_existing":
                state["travelers_count"] = parsed_data["travelers_count"]
            if state.get("travelers_count") is None:
                state["travelers_count"] = 1
                self.logger.info("✅ Set default travelers_count = 1")
            
            if parsed_data.get("budget_range") and parsed_data["budget_range"] != "keep_existing":
                state["budget_range"] = parsed_data["budget_range"]
            
            query_type = parsed_data.get("query_type", "multi_aspect")
            state["query_type"] = query_type
            state["needs_itinerary"] = (query_type == "full_itinerary")
            
            if parsed_data.get("interests"):
                if not state.get("user_preferences"):
                    state["user_preferences"] = {}
                state["user_preferences"]["interests"] = parsed_data["interests"]
            
            state["messages"].append(
                f"Query parsed: Destination={state['destination']}, "
                f"Query type={query_type}, Dates={state['travel_dates']}"
            )
            
            self.logger.info(
                f"✅ Query parsed - Destination: {state['destination']}, "
                f"Query type: {query_type}, Dates: {state['travel_dates']}"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to parse query: {str(e)}")
            state["errors"].append(f"Query parsing failed: {str(e)}")
            if state.get("travelers_count") is None:
                state["travelers_count"] = 1
        
        return state
    
    def _parse_llm_extraction(self, llm_response: str) -> Dict[str, Any]:
        """Parse the LLM's structured response"""
        result = {
            "destination": None,
            "origin": None,
            "travel_dates": [],
            "travelers_count": 1,
            "budget_range": None,
            "interests": [],
            "query_type": "multi_aspect"
        }
        
        lines = llm_response.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if ':' not in line:
                continue
            
            key, value = line.split(':', 1)
            key = key.strip().lower()
            value = value.strip()
            
            if value.lower() in ["not specified", "not mentioned", "none", "", "keep existing"]:
                if "keep existing" in value.lower():
                    # Mark as keep_existing
                    if "destination" in key:
                        result["destination"] = "keep_existing"
                    elif "origin" in key:
                        result["origin"] = "keep_existing"
                    elif "travel dates" in key or "dates" in key:
                        result["travel_dates"] = ["keep_existing"]
                    elif "travelers" in key or "count" in key:
                        result["travelers_count"] = "keep_existing"
                    elif "budget" in key:
                        result["budget_range"] = "keep_existing"
                continue
            
            if "destination" in key:
                result["destination"] = value
            elif "origin" in key:
                result["origin"] = value
            elif "travel dates" in key or "dates" in key:
                dates = [d.strip().strip("[]").strip("'\"") for d in value.split(',')]
                result["travel_dates"] = [
                d for d in dates if d and d.lower() not in ["not specified", "keep existing"]
                 ]
            elif "travelers" in key or "count" in key:
                try:
                    result["travelers_count"] = int(value.split()[0])
                except:
                    result["travelers_count"] = 1
            elif "budget" in key:
                result["budget_range"] = value
            elif "interest" in key:
                interests = [i.strip() for i in value.split(',')]
                result["interests"] = [i for i in interests if i and i.lower() != "not specified"]
            elif "query type" in key or "query_type" in key:
                result["query_type"] = value.lower().replace(" ", "_")
        
        return result
    
    async def _validate_params_node(self, state: OrchestratorState) -> OrchestratorState:
        """Validate extracted parameters based on query type"""
        self.logger.info("✔️  Validating travel parameters")
        
        await self._send_streaming_update(
            session_id=state["session_id"],
            agent="orchestrator",
            message="Validating travel parameters...",
            update_type="progress",
            progress_percent=20
        )
        
        errors = []
        query_type = state.get("query_type", "multi_aspect")
        update_type = state.get("update_type")
        is_follow_up = state.get("is_follow_up", False)
        
        # For follow-up updates, validation is more lenient - we use existing context
        if is_follow_up and update_type in ["budget_update", "itinerary_update"]:
            # Only validate that we have the minimum context from previous conversation
            if not state.get("destination"):
                errors.append("Cannot update: No destination found in conversation history")
            else:
                self.logger.info(f"✅ Update validation passed - using context: destination={state['destination']}")
                state["workflow_status"] = "validated"
                state["messages"].append(f"Update validated: {update_type}")
                return state
        
        # Standard validation for new queries
        if query_type == "weather_only":
            if not state.get("destination"):
                errors.append("Destination is required for weather information")
            if not state.get("travel_dates") or len(state["travel_dates"]) == 0:
                errors.append("Travel date is required for weather information")
        
        elif query_type in ["events_only", "maps_only", "budget_only"]:
            if not state.get("destination"):
                errors.append("Destination is required")
        
        elif query_type == "full_itinerary":
            if not state.get("destination"):
                errors.append("Destination is required")
            if not state.get("travel_dates") or len(state["travel_dates"]) == 0:
                errors.append("Travel dates are required for itinerary planning")
        
        else:  # multi_aspect
            if not state.get("destination"):
                errors.append("Destination is required")
        
        if errors:
            state["errors"].extend(errors)
            state["workflow_status"] = "validation_failed"
            self.logger.error(f"Validation failed: {errors}")
        else:
            state["workflow_status"] = "validated"
            state["messages"].append("Parameters validated successfully")
            self.logger.info("✅ Parameters validated")
        
        return state
    
    def _should_continue_after_validation(self, state: OrchestratorState) -> str:
        """Decide whether to continue workflow after validation"""
        if state["workflow_status"] == "validated":
            return "dispatch"
        return "end"
    
    async def _dispatch_agents_node(self, state: OrchestratorState) -> OrchestratorState:
        """Dispatch requests to specialized agents based on query type and updates"""
        self.logger.info("📤 Dispatching requests to specialized agents")
        
        await self._send_streaming_update(
            session_id=state["session_id"],
            agent="orchestrator",
            message="Dispatching requests to specialized agents...",
            update_type="progress",
            progress_percent=30
        )
        
        session_id = state["session_id"]
        query_type = state.get("query_type", "multi_aspect")
        update_type = state.get("update_type")
        is_follow_up = state.get("is_follow_up", False)
        
        # Check if agents were pre-determined (e.g., for updates)
        if state.get("agents_to_execute"):
            agents_to_call = state["agents_to_execute"]
            self.logger.info(f"🎯 Using pre-determined agents: {agents_to_call}")
        else:
            # Determine which agents to call based on query type
            agents_to_call = []
            
            if query_type == "weather_only":
                agents_to_call = ["weather"]
                self.logger.info("🌤️  Query type: weather_only")
            
            elif query_type == "events_only":
                agents_to_call = ["events"]
                self.logger.info("🎉 Query type: events_only")
            
            elif query_type == "maps_only":
                agents_to_call = ["maps"]
                self.logger.info("🗺️  Query type: maps_only")
            
            elif query_type == "budget_only":
                agents_to_call = ["budget"]
                self.logger.info("💰 Query type: budget_only")
            
            elif query_type == "full_itinerary":
                # Check if we already have data and just need itinerary update
                if is_follow_up and all([
                    state.get("weather_data"),
                    state.get("events_data"),
                    state.get("budget_data")
                ]):
                    agents_to_call = ["itinerary"]
                    self.logger.info("📋 Itinerary update - reusing existing data")
                else:
                    agents_to_call = ["weather", "events", "maps", "budget"]
                    self.logger.info("📋 Full itinerary - fetching all data")
            
                

            else:  # multi_aspect
                self.logger.info("🔀 Query type: multi_aspect - selective dispatch")
                
                if state.get("travel_dates"):
                    agents_to_call.append("weather")
                
                if state.get("user_preferences"):
                    agents_to_call.append("events")
                
                if state.get("origin"):
                    agents_to_call.append("maps")
                
                if state.get("budget_range") or (state.get("travelers_count") and state["travelers_count"] > 1):
                    agents_to_call.append("budget")
            
            state["agents_to_execute"] = agents_to_call
        
        state["agent_statuses"] = {agent: "pending" for agent in agents_to_call}
        
        # Dispatch requests in parallel
        dispatch_tasks = []
        
        if "weather" in agents_to_call:
            dispatch_tasks.append(self._dispatch_weather(state))
        
        if "events" in agents_to_call:
            dispatch_tasks.append(self._dispatch_events(state))
        
        if "maps" in agents_to_call:
            dispatch_tasks.append(self._dispatch_maps(state))
        
        if "budget" in agents_to_call:
            dispatch_tasks.append(self._dispatch_budget(state))
        
        await asyncio.gather(*dispatch_tasks, return_exceptions=True)
        
        state["messages"].append(
            f"Dispatched {len(dispatch_tasks)} agent requests"
        )
        self.logger.info(f"✅ Dispatched {len(dispatch_tasks)} agents: {agents_to_call}")
        
        return state

    async def _dispatch_weather(self, state: OrchestratorState):
        """Dispatch request to weather agent"""
        request = {
            "request_id": f"weather_{uuid.uuid4().hex[:8]}",
            "session_id": state["session_id"],
            "agent": "weather",
            "action": "request",
            "payload": {
                "destination": state["destination"],
                "travel_dates": state["travel_dates"]
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        state["agent_statuses"]["weather"] = "processing"
        channel = RedisChannels.WEATHER_REQUEST
        await self.redis_client.publish(channel, request)
        self.logger.info(f"📡 Dispatched weather request")
        await self._send_streaming_update(
        session_id=state["session_id"],
        agent="weather",
        message="Weather agent started processing",
        update_type="agent_start"
    )
    
    async def _dispatch_events(self, state: OrchestratorState):
        """Dispatch request to events agent"""
        interests = None
        if state.get("user_preferences"):
            interests = state["user_preferences"].get("interests")
        
        request = {
            "request_id": f"events_{uuid.uuid4().hex[:8]}",
            "session_id": state["session_id"],
            "agent": "events",
            "action": "request",
            "payload": {
                "destination": state["destination"],
                "travel_dates": state["travel_dates"],
                "interests": interests
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        state["agent_statuses"]["events"] = "processing"
        channel = RedisChannels.EVENTS_REQUEST
        await self.redis_client.publish(channel, request)
        self.logger.info(f"📡 Dispatched events request")
        await self._send_streaming_update(
        session_id=state["session_id"],
        agent="events",
        message="Events agent started processing",
        update_type="agent_start"
    )
    
    async def _dispatch_maps(self, state: OrchestratorState):
        """Dispatch request to maps agent"""
        request = {
            "request_id": f"maps_{uuid.uuid4().hex[:8]}",
            "session_id": state["session_id"],
            "agent": "maps",
            "action": "request",
            "payload": {
                "origin": state.get("origin", "Current Location"),
                "destination": state["destination"]
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        state["agent_statuses"]["maps"] = "processing"
        channel = RedisChannels.MAPS_REQUEST
        await self.redis_client.publish(channel, request)
        self.logger.info(f"📡 Dispatched maps request")
        await self._send_streaming_update(
        session_id=state["session_id"],
        agent="maps",
        message="Maps agent started processing",
        update_type="agent_start"
    )

    
    async def _dispatch_budget(self, state: OrchestratorState):
        """Dispatch request to budget agent"""
        request = {
            "request_id": f"budget_{uuid.uuid4().hex[:8]}",
            "session_id": state["session_id"],
            "agent": "budget",
            "action": "request",
            "payload": {
                "destination": state["destination"],
                "travel_dates": state["travel_dates"],
                "travelers_count": state["travelers_count"],
                "budget_range": state.get("budget_range"),
                # Include modification context for updates
                "is_update": state.get("is_follow_up", False),
                "update_request": state.get("user_query") if state.get("update_type") == "budget_update" else None
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        state["agent_statuses"]["budget"] = "processing"
        channel = RedisChannels.BUDGET_REQUEST
        await self.redis_client.publish(channel, request)
        self.logger.info(f"📡 Dispatched budget request")
        await self._send_streaming_update(
        session_id=state["session_id"],
        agent="budget",
        message="Budget agent started processing",
        update_type="agent_start"
    )
    
    async def _collect_responses_node(self, state: OrchestratorState) -> OrchestratorState:
        """Collect responses from agents incrementally with streaming"""
        self.logger.info("📥 Collecting responses from agents")
        
        await self._send_streaming_update(
            session_id=state["session_id"],
            agent="orchestrator",
            message="Waiting for agent responses...",
            update_type="progress",
            progress_percent=40
        )
        
        session_id = state["session_id"]
        agents = state["agents_to_execute"]
        
        # Setup response collection
        futures = {agent: asyncio.Future() for agent in agents}
        subscriptions = {}
        
        async def create_handler(agent_name):
            async def handler(data):
                if not futures[agent_name].done():
                    futures[agent_name].set_result(data)
            return handler
        
        # Subscribe to response channels
        for agent in agents:
            channel = RedisChannels.get_response_channel(agent, session_id)
            self.logger.info(f"📡 Subscribed to channel: {channel}")
            subscriptions[agent] = await self.redis_client.subscribe(
                channel,
                await create_handler(agent)
            )
        
        # Collect responses as they arrive
        pending_agents = set(agents)
        completed_count = 0
        total_agents = len(agents)
        
        timeout = 30  # 30 seconds timeout per agent
        
        while pending_agents:
            try:
                done, _ = await asyncio.wait(
                    [futures[agent] for agent in pending_agents],
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                for future in done:
                    agent_name = next(a for a in pending_agents if futures[a] == future)
                    response_data = future.result() if future.done() and not future.exception() else None
                    
                    if response_data:
                        await self._process_agent_response(state, agent_name, response_data)
                        state["agent_statuses"][agent_name] = "completed"
                        completed_count += 1
                        
                        # Stream update about completion
                        progress = 40 + int((completed_count / total_agents) * 40)
                        await self._send_streaming_update(
                            session_id=session_id,
                            agent="orchestrator",
                            message=f"{agent_name.title()} agent completed ({completed_count}/{total_agents})",
                            update_type="progress",
                            progress_percent=progress,
                            data={f"{agent_name}_complete": True}
                        )
                    else:
                        state["agent_statuses"][agent_name] = "timeout"
                        self.logger.warning(f"⏱️ Timeout for {agent_name}")
                        await self._send_streaming_update(
                        session_id=session_id,
                        agent=agent_name,
                        message=f"{agent_name.title()} agent timed out",
                        update_type="error"
                    )
                
                    
                    pending_agents.remove(agent_name)
                
            except asyncio.TimeoutError:
                # Timeout for remaining agents
                for agent in pending_agents:
                    state["agent_statuses"][agent] = "timeout"
                    self.logger.warning(f"⏱️ Timeout for {agent}")
                break
        
        # Cleanup subscriptions
        for subscription_id in subscriptions.values():
            await self.redis_client.unsubscribe(subscription_id)
        
        completed = sum(1 for s in state["agent_statuses"].values() if s == "completed")
        state["messages"].append(f"Collected {completed}/{len(agents)} agent responses")
        
        return state
    
    async def _process_agent_response(
        self,
        state: OrchestratorState,
        agent_name: str,
        response_data: Dict[str, Any]
    ):
        """Process individual agent response and update state"""
        success = response_data.get("success", False)
        data = response_data.get("data")
        
        if success and data:
            if agent_name == "weather":
                state["weather_data"] = data
            elif agent_name == "events":
                state["events_data"] = data
            elif agent_name == "maps":
                state["maps_data"] = data
            elif agent_name == "budget":
                state["budget_data"] = data
            elif agent_name == "itinerary":
                state["itinerary_data"] = data
            
            self.logger.info(f"✅ {agent_name} completed successfully")
            await self._send_streaming_update(
                session_id=state["session_id"],
                agent=agent_name,
                message=f"{agent_name.title()} agent completed successfully",
                update_type="agent_update",
                data={f"{agent_name}_data": data}
            )
        else:
            error = response_data.get("error", "Unknown error")
            state["errors"].append(f"{agent_name}: {error}")
            self.logger.error(f"❌ {agent_name} failed: {error}")
            await self._send_streaming_update(
                session_id=state["session_id"],
                agent=agent_name,
                message=f"{agent_name.title()} agent failed: {error}",
                update_type="error"
            )
    
    async def _synthesize_plan_node(self, state: OrchestratorState) -> OrchestratorState:
        """Synthesize final travel plan from all agent data"""
        self.logger.info("🎨 Synthesizing final travel plan")
        
        # Check if user wants a full itinerary
        if not state.get("needs_itinerary", False):
            self.logger.info("⏭️ Skipping itinerary synthesis - not requested by user")
            state["messages"].append("Skipped itinerary synthesis (user requested specific info only)")
            return state
        
        # User wants full itinerary - proceed with synthesis
        await self._send_streaming_update(
            session_id=state["session_id"],
            agent="orchestrator",
            message="Creating your personalized travel itinerary...",
            update_type="progress",
            progress_percent=85
        )
        
        # Check if we have enough data for itinerary synthesis
        has_required_data = (
            state.get("destination") and 
            state.get("travel_dates") and
            len(state.get("travel_dates", [])) > 0
        )
        
        if has_required_data:
            self.logger.info("📋 Dispatching to itinerary agent for synthesis")
            
            # Dispatch to itinerary agent with all collected data
            await self._dispatch_itinerary(state)
            
            # Wait for itinerary response
            response = await self._wait_for_itinerary_response(state)
            
            if response:
                await self._process_agent_response(state, "itinerary", response)
                state["agent_statuses"]["itinerary"] = "completed"
                state["messages"].append("Itinerary synthesis completed")
                
                # Send streaming update about itinerary completion
                await self._send_streaming_update(
                    session_id=state["session_id"],
                    agent="orchestrator",
                    message="Personalized itinerary created",
                    update_type="progress",
                    progress_percent=95,
                    data={"itinerary_complete": True}
                )
            else:
                state["agent_statuses"]["itinerary"] = "timeout"
                state["errors"].append("Itinerary agent timeout")
                state["messages"].append("Created basic travel summary (itinerary timeout)")
                self.logger.warning("⏱️ Itinerary agent timed out")
        else:
            # Not enough data to create itinerary
            state["messages"].append("Skipped itinerary synthesis (insufficient data)")
            self.logger.warning("⚠️ Insufficient data for itinerary synthesis")
        
        return state
    
    async def _dispatch_itinerary(self, state: OrchestratorState):
        """Dispatch request to itinerary agent for synthesis"""
        is_update = state.get("is_follow_up", False) and state.get("itinerary_data") is not None
        
        request = {
            "request_id": f"itinerary_{uuid.uuid4().hex[:8]}",
            "session_id": state["session_id"],
            "agent": "itinerary",
            "action": "request",
            "payload": {
                "destination": state["destination"],
                "origin": state.get("origin"),
                "travel_dates": state["travel_dates"],
                "travelers_count": state["travelers_count"],
                "budget_range": state.get("budget_range"),
                # Pass all collected agent data
                "weather_data": state.get("weather_data"),
                "events_data": state.get("events_data"),
                "maps_data": state.get("maps_data"),
                "route_data": state.get("maps_data"),  # Alias for compatibility
                "budget_data": state.get("budget_data"),
                "user_preferences": state.get("user_preferences"),
                # NEW: Pass context for updates
                "is_update": is_update,
                "previous_itinerary": state.get("itinerary_data") if is_update else None,
                "update_request": state.get("user_query") if is_update else None,
                "conversation_history": state.get("conversation_history", [])
            },
            "metadata": {
                "timeout_ms": 45000  # 45 second timeout for synthesis
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        channel = RedisChannels.ITINERARY_REQUEST
        await self.redis_client.publish(channel, request)
        
        self.logger.info(f"📡 Dispatched itinerary synthesis request (is_update={is_update})")
        await self._send_streaming_update(
        session_id=state["session_id"],
        agent="itinerary",
        message="Itinerary agent started synthesizing your plan",
        update_type="agent_start"
    )
    
    async def _wait_for_itinerary_response(
        self,
        state: OrchestratorState,
        timeout: float = 50.0  # Longer timeout for synthesis
    ) -> Optional[Dict[str, Any]]:
        """Wait for itinerary agent response"""
        session_id = state["session_id"]
        channel = RedisChannels.get_response_channel("itinerary", session_id)
        
        self.logger.info(f"📡 Subscribed to channel: {channel}")
        
        response_future = asyncio.Future()
        
        async def handler(data):
            if not response_future.done():
                self.logger.info(f"📥 Received itinerary response")
                response_future.set_result(data)
        
        subscription_id = await self.redis_client.subscribe(channel, handler)
        
        try:
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            self.logger.warning(f"⏱️ Timeout waiting for itinerary ({timeout}s)")
            return None
        except Exception as e:
            self.logger.error(f"❌ Error waiting for itinerary: {str(e)}")
            return None
        finally:
            await self.redis_client.unsubscribe(subscription_id)
    
    async def _finalize_node(self, state: OrchestratorState) -> OrchestratorState:
        """Finalize workflow and prepare final response"""
        self.logger.info("🎯 Finalizing travel plan")
        
        state["end_time"] = datetime.utcnow().isoformat()
        state["workflow_status"] = "completed"
        
        # Count successful agents
        completed = sum(1 for s in state["agent_statuses"].values() if s == "completed")
        total = len(state["agent_statuses"])
        
        # Add assistant response to conversation history
        state["conversation_history"].append({
            "role": "assistant",
            "content": f"Completed processing: {completed}/{total} agents successful",
            "timestamp": datetime.utcnow().isoformat(),
            "agents_executed": state["agents_to_execute"]
        })
        
        # Send final streaming update
        await self._send_streaming_update(
            session_id=state["session_id"],
            agent="orchestrator",
            message=f"Travel plan completed! ({completed}/{total} agents successful)",
            update_type="completed",
            progress_percent=100,
            data={
                "weather_data": state.get("weather_data"),
                "events_data": state.get("events_data"),
                "maps_data": state.get("maps_data"),
                "budget_data": state.get("budget_data"),
                "itinerary_data": state.get("itinerary_data")
            }
        )
        
        state["messages"].append(f"Workflow completed with {completed}/{total} agents")
        
        # Save final state to Redis with extended TTL for memory
        await self.redis_client.set_state(
            state["session_id"],
            dict(state),
            ttl=86400  # 24 hours for longer memory retention
        )
        
        self.logger.info(f"🎉 Workflow completed successfully - Memory saved")
        
        return state
    
    # ==================== STREAMING ====================
    
    async def _send_streaming_update(
        self,
        session_id: str,
        agent: str,
        message: str,
        update_type: str,
        progress_percent: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None
    ):
        """Send streaming update via Redis"""
        try:
            update = {
                "session_id": session_id,
                "agent": agent,
                "type": update_type,
                "message": message,
                "progress_percent": progress_percent,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            channel = RedisChannels.get_streaming_channel(session_id)
            await self.redis_client.publish(channel, update)
            
        except Exception as e:
            self.logger.warning(f"Failed to send streaming update: {str(e)}")
    
    # ==================== PUBLIC API ====================
    
    async def process_query(
        self, 
        user_query: str, 
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a user travel query with memory support
        
        Args:
            user_query: Natural language travel query from user
            session_id: Optional session ID for tracking (required for follow-ups)
            
        Returns:
            Final travel plan with all agent responses
        """
        # Generate session ID if not provided
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"
            self.logger.info(f"🆕 Generated new session ID: {session_id}")
        else:
            self.logger.info(f"🔄 Using existing session ID: {session_id}")
        
        # Connect to Redis
        await self.redis_client.connect()
        
        # Create initial state (will be populated by load_memory_node)
        initial_state = {
            "session_id": session_id,
            "user_query": user_query,
            "is_follow_up": False,
            "conversation_history": [],
            "destination": None,
            "origin": None,
            "travel_dates": [],
            "travelers_count": None,
            "query_type": "multi_aspect",
            "update_type": None,
            "budget_range": None,
            "user_preferences": None,
            "needs_itinerary": False,
            "agents_to_execute": [],
            "agent_statuses": {},
            "agent_responses": {},
            "weather_data": None,
            "events_data": None,
            "maps_data": None,
            "budget_data": None,
            "itinerary_data": None,
            "messages": [],
            "errors": [],
            "workflow_status": "initialized",
            "start_time": datetime.utcnow().isoformat(),
            "end_time": None
        }
        
        self.logger.info(
            f"🎪 Starting orchestration workflow\n"
            f"   Session: {session_id}\n"
            f"   Query: {user_query}"
        )
        
        try:
            # Run the workflow
            final_state = await self.graph.ainvoke(initial_state)
            
            return {
                "session_id": session_id,
                "status": final_state["workflow_status"],
                "is_follow_up": final_state.get("is_follow_up", False),
                "update_type": final_state.get("update_type"),
                "destination": final_state.get("destination"),
                "travel_dates": final_state.get("travel_dates"),
                "needs_itinerary": final_state.get("needs_itinerary"),
                "weather": final_state.get("weather_data"),
                "events": final_state.get("events_data"),
                "maps": final_state.get("maps_data"),
                "budget": final_state.get("budget_data"),
                "itinerary": final_state.get("itinerary_data"),
                "messages": final_state["messages"],
                "errors": final_state["errors"],
                "agent_statuses": final_state["agent_statuses"],
                "conversation_history": final_state.get("conversation_history", [])
            }
            
        except Exception as e:
            self.logger.error(f"Orchestration failed: {str(e)}", exc_info=True)
            raise
    
    async def get_session_memory(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve session memory from Redis
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session state or None if not found
        """
        await self.redis_client.connect()
        return await self.redis_client.get_state(session_id)
    
    async def clear_session_memory(self, session_id: str) -> bool:
        """
        Clear session memory from Redis
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if deleted successfully
        """
        await self.redis_client.connect()
        return await self.redis_client.delete_state(session_id)
    
    async def extend_session_memory(self, session_id: str, hours: int = 24) -> bool:
        """
        Extend session memory TTL
        
        Args:
            session_id: Session identifier
            hours: Hours to extend
            
        Returns:
            True if extended successfully
        """
        await self.redis_client.connect()
        return await self.redis_client.extend_state_ttl(session_id, ttl=hours * 3600)


# ==================== HELPER FUNCTIONS ====================

async def create_orchestrator(
    redis_client: Optional[RedisClient] = None,
    gemini_api_key: Optional[str] = None
) -> OrchestratorAgent:
    """
    Create and initialize an orchestrator agent with memory support
    
    Args:
        redis_client: Optional Redis client instance
        gemini_api_key: Optional Gemini API key
        
    Returns:
        Initialized OrchestratorAgent
    """
    orchestrator = OrchestratorAgent(
        redis_client=redis_client,
        gemini_api_key=gemini_api_key
    )
    
    # Connect Redis if not already connected
    if orchestrator.redis_client:
        await orchestrator.redis_client.connect()
    
    return orchestrator
# ==================== STANDALONE RUNNER ====================

async def run_orchestrator_standalone():
    """Run the orchestrator as a standalone service for testing"""
    from app.messaging.redis_client import get_redis_client
    from app.config.settings import settings
    
    # Get Redis client
    redis_client = get_redis_client()
    await redis_client.connect()
    
    # Create orchestrator
    orchestrator = OrchestratorAgent(
        redis_client=redis_client,
        gemini_api_key=settings.google_api_key
    )
    
    print("🎪 Orchestrator Agent is ready!")
    print("\nExample queries:")
    print("  1. 'Plan my trip to Paris from Dec 15-20'")
    print("  2. 'What's the weather in Tokyo next week?'")
    print("  3. 'Find events in New York this weekend'")
    print("  4. 'Create a complete itinerary for London, 3 days'")
    print("\nEnter a query (or 'quit' to exit):\n")
    
    try:
        while True:
            user_input = input("> ")
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                break
            
            if not user_input.strip():
                continue
            
            print("\n🔄 Processing...\n")
            
            try:
                result = await orchestrator.process_query(user_input)
                
                print(f"\n✅ Status: {result['status']}")
                print(f"📍 Destination: {result.get('destination')}")
                print(f"📅 Travel Dates: {result.get('travel_dates')}")
                print(f"📋 Needs Itinerary: {result.get('needs_itinerary')}")
                print(f"\n🤖 Agent Statuses:")
                for agent, status in result['agent_statuses'].items():
                    emoji = "✅" if status == "completed" else "⏱️" if status == "timeout" else "❌"
                    print(f"   {emoji} {agent}: {status}")
                
                if result.get('itinerary'):
                    print(f"\n📖 Itinerary created: {result['itinerary'].get('total_days')} days")
                
                if result.get('errors'):
                    print(f"\n⚠️ Errors: {result['errors']}")
                
                print("\n" + "="*60 + "\n")
                
            except Exception as e:
                print(f"\n❌ Error: {str(e)}\n")
    
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down orchestrator...")
    
    finally:
        await redis_client.disconnect()
        print("✅ Orchestrator stopped")


if __name__ == "__main__":
    import asyncio
    
    asyncio.run(run_orchestrator_standalone())