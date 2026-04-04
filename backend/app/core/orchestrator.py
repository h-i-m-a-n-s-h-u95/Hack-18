from typing import Dict, Any, List, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
import asyncio
from datetime import datetime
import logging

from app.core.state import (
    TravelState, create_initial_state, update_agent_status,
    add_streaming_update, is_workflow_complete, WorkflowStatus, AgentStatus
)
from app.messaging.redis_client import RedisClient, RedisChannels, get_redis_client
from app.messaging.protocols import (
    MessageFactory, AgentType, AgentResponse
)
from app.config.settings import settings


logger = logging.getLogger(__name__)


class TravelOrchestrator:
    """
    Grand Orchestrator for coordinating travel planning agents
    
    Uses LangGraph for workflow management and Redis Pub/Sub for agent communication
    """
    
    def __init__(self, redis_client: Optional[RedisClient] = None):
        self.redis_client = redis_client or get_redis_client()
        self.graph = self._build_graph()
        self.logger = logging.getLogger("orchestrator")
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow"""
        
        # Create graph with TravelState
        workflow = StateGraph(TravelState)
        
        # Add nodes
        workflow.add_node("initialize", self._initialize_node)
        workflow.add_node("route_requests", self._route_requests_node)
        workflow.add_node("dispatch_parallel", self._dispatch_parallel_node)
        workflow.add_node("collect_responses", self._collect_responses_node)
        workflow.add_node("validate", self._validate_node)
        workflow.add_node("synthesize", self._synthesize_node)
        workflow.add_node("finalize", self._finalize_node)
        
        # Define edges
        workflow.set_entry_point("initialize")
        workflow.add_edge("initialize", "route_requests")
        workflow.add_edge("route_requests", "dispatch_parallel")
        workflow.add_edge("dispatch_parallel", "collect_responses")
        workflow.add_edge("collect_responses", "validate")
        
        # Conditional edge after validation
        workflow.add_conditional_edges(
            "validate",
            self._should_synthesize,
            {
                "synthesize": "synthesize",
                "finalize": "finalize"
            }
        )
        
        workflow.add_edge("synthesize", "finalize")
        workflow.add_edge("finalize", END)
        
        # Compile with checkpointer for state persistence
        return workflow.compile(checkpointer=MemorySaver())
    
    # ==================== WORKFLOW NODES ====================
    
    async def _initialize_node(self, state: TravelState) -> TravelState:
        """Initialize the workflow"""
        self.logger.info(f"🎪 Initializing workflow for session: {state['session_id']}")
        
        state["workflow_status"] = WorkflowStatus.INITIALIZED
        state["messages"].append("Workflow initialized")
        
        # Save initial state to Redis
        await self.redis_client.set_state(state["session_id"], dict(state))
        
        return state
    
    async def _route_requests_node(self, state: TravelState) -> TravelState:
        """Determine which agents need to be called"""
        self.logger.info("🧭 Routing requests to appropriate agents")
        
        state["workflow_status"] = WorkflowStatus.ROUTING
        
        # For now, we call all main agents (weather, events, maps, budget)
        # In a more advanced version, this could be LLM-driven based on user query
        agents_to_call = ["weather", "events", "maps", "budget"]
        
        state["agents_to_execute"] = agents_to_call
        state["messages"].append(f"Routing to agents: {', '.join(agents_to_call)}")
        
        # Update state in Redis
        await self.redis_client.set_state(state["session_id"], dict(state))
        
        return state
    
    async def _dispatch_parallel_node(self, state: TravelState) -> TravelState:
        """Dispatch requests to agents in parallel"""
        self.logger.info("📤 Dispatching parallel requests to agents")
        
        state["workflow_status"] = WorkflowStatus.FETCHING
        
        session_id = state["session_id"]
        
        # Create request tasks for each agent
        tasks = []
        
        if "weather" in state["agents_to_execute"]:
            tasks.append(self._dispatch_weather_request(state))
        
        if "events" in state["agents_to_execute"]:
            tasks.append(self._dispatch_events_request(state))
        
        if "maps" in state["agents_to_execute"]:
            tasks.append(self._dispatch_maps_request(state))
        
        if "budget" in state["agents_to_execute"]:
            tasks.append(self._dispatch_budget_request(state))
        
        # Dispatch all requests
        await asyncio.gather(*tasks)
        
        state["messages"].append(f"Dispatched {len(tasks)} agent requests")
        
        # Update state in Redis
        await self.redis_client.set_state(state["session_id"], dict(state))
        
        return state
    
    async def _dispatch_weather_request(self, state: TravelState):
        """Dispatch request to weather agent"""
        request = MessageFactory.create_weather_request(
            session_id=state["session_id"],
            destination=state["destination"],
            travel_dates=state["travel_dates"],
            timeout_ms=settings.timeout_weather
        )
        
        # Update agent status
        state = update_agent_status(state, "weather", AgentStatus.PROCESSING)
        
        # Publish to weather request channel
        channel = RedisChannels.WEATHER_REQUEST
        await self.redis_client.publish(channel, request.dict())
        
        self.logger.info(f"📡 Dispatched weather request to {channel}")
    
    async def _dispatch_events_request(self, state: TravelState):
        """Dispatch request to events agent"""
        interests = None
        if state.get("user_preferences"):
            interests = state["user_preferences"].get("interests")
        
        request = MessageFactory.create_events_request(
            session_id=state["session_id"],
            destination=state["destination"],
            travel_dates=state["travel_dates"],
            interests=interests,
            timeout_ms=settings.timeout_events
        )
        
        state = update_agent_status(state, "events", AgentStatus.PROCESSING)
        
        channel = RedisChannels.EVENTS_REQUEST
        await self.redis_client.publish(channel, request.dict())
        
        self.logger.info(f"📡 Dispatched events request to {channel}")
    
    async def _dispatch_maps_request(self, state: TravelState):
        """Dispatch request to maps agent"""
        request = MessageFactory.create_maps_request(
            session_id=state["session_id"],
            origin=state["origin"],
            destination=state["destination"],
            timeout_ms=settings.timeout_maps
        )
        
        state = update_agent_status(state, "maps", AgentStatus.PROCESSING)
        
        channel = RedisChannels.MAPS_REQUEST
        await self.redis_client.publish(channel, request.dict())
        
        self.logger.info(f"📡 Dispatched maps request to {channel}")
    
    async def _dispatch_budget_request(self, state: TravelState):
        """Dispatch request to budget agent"""
        request = MessageFactory.create_budget_request(
            session_id=state["session_id"],
            destination=state["destination"],
            travel_dates=state["travel_dates"],
            travelers_count=state["travelers_count"],
            budget_range=state.get("budget_range"),
            timeout_ms=settings.timeout_budget
        )
        
        state = update_agent_status(state, "budget", AgentStatus.PROCESSING)
        
        channel = RedisChannels.BUDGET_REQUEST
        await self.redis_client.publish(channel, request.dict())
        
        self.logger.info(f"📡 Dispatched budget request to {channel}")
    
    async def _collect_responses_node(self, state: TravelState) -> TravelState:
        """Collect responses from all agents"""
        self.logger.info("📥 Collecting responses from agents")
        
        session_id = state["session_id"]
        agents = state["agents_to_execute"]
        
        # Subscribe to response channels
        response_channels = {
            agent: RedisChannels.get_response_channel(agent, session_id)
            for agent in agents
        }
        
        # Collect responses with timeout
        responses = await self._wait_for_responses(
            response_channels,
            timeout=settings.orchestrator_timeout / 1000
        )
        
        # Process each response
        for agent_name, response_data in responses.items():
            if response_data:
                await self._process_agent_response(state, agent_name, response_data)
            else:
                # Timeout occurred
                state = update_agent_status(state, agent_name, AgentStatus.TIMEOUT)
                self.logger.warning(f"⏱️ Timeout waiting for {agent_name}")
        
        state["messages"].append(f"Collected responses from {len(responses)} agents")
        
        # Update state in Redis
        await self.redis_client.set_state(state["session_id"], dict(state))
        
        return state
    
    async def _wait_for_responses(
        self,
        channels: Dict[str, str],
        timeout: float
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """Wait for responses from multiple channels with timeout"""
        
        responses = {agent: None for agent in channels.keys()}
        futures = {agent: asyncio.Future() for agent in channels.keys()}
        subscriptions = {}
        
        # Create handlers for each channel
        for agent, channel in channels.items():
            async def create_handler(agent_name):
                async def handler(data):
                    if not futures[agent_name].done():
                        futures[agent_name].set_result(data)
                return handler
            
            subscription_id = await self.redis_client.subscribe(
                channel=channel,
                handler=await create_handler(agent)
            )
            subscriptions[agent] = subscription_id
        
        try:
            # Wait for all responses or timeout
            await asyncio.wait_for(
                asyncio.gather(*futures.values(), return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout after {timeout}s waiting for responses")
        
        # Collect results
        for agent, future in futures.items():
            if future.done() and not future.exception():
                responses[agent] = future.result()
        
        # Cleanup subscriptions
        for subscription_id in subscriptions.values():
            await self.redis_client.unsubscribe(subscription_id)
        
        return responses
    
    async def _process_agent_response(
        self,
        state: TravelState,
        agent_name: str,
        response_data: Dict[str, Any]
    ):
        """Process response from an agent"""
        
        success = response_data.get("success", False)
        data = response_data.get("data")
        error = response_data.get("error")
        
        if success and data:
            # Store agent data in state
            if agent_name == "weather":
                state["weather_data"] = data.get("weather_forecast", [])
                state["weather_complete"] = True
            elif agent_name == "events":
                state["events_data"] = data.get("events", [])
                state["events_complete"] = True
            elif agent_name == "maps":
                state["route_data"] = data.get("route_info")
                state["maps_complete"] = True
            elif agent_name == "budget":
                state["budget_data"] = data.get("budget_breakdown")
                state["budget_complete"] = True
            
            # Update status
            state = update_agent_status(state, agent_name, AgentStatus.COMPLETED)
            self.logger.info(f"✅ {agent_name} completed successfully")
            
        else:
            # Handle failure
            state = update_agent_status(
                state, 
                agent_name, 
                AgentStatus.FAILED,
                error_message=error
            )
            self.logger.error(f"❌ {agent_name} failed: {error}")
    
    async def _validate_node(self, state: TravelState) -> TravelState:
        """Validate that we have sufficient data to proceed"""
        self.logger.info("🔍 Validating collected data")
        
        state["workflow_status"] = WorkflowStatus.VALIDATING
        
        # Check which agents completed successfully
        completed = [
            agent for agent in state["agents_to_execute"]
            if state[f"{agent}_complete"]
        ]
        
        failed = [
            agent for agent in state["agents_to_execute"]
            if not state[f"{agent}_complete"]
        ]
        
        # Determine if we have enough data to synthesize
        critical_agents = ["weather", "maps"]  # Minimum required
        has_critical_data = all(agent in completed for agent in critical_agents)
        
        if has_critical_data:
            state["workflow_status"] = WorkflowStatus.SYNTHESIZING
            state["messages"].append(f"Validation passed. Completed: {', '.join(completed)}")
        else:
            state["workflow_status"] = WorkflowStatus.PARTIAL
            state["messages"].append(
                f"Insufficient data. Failed: {', '.join(failed)}"
            )
        
        # Update state in Redis
        await self.redis_client.set_state(state["session_id"], dict(state))
        
        return state
    
    def _should_synthesize(self, state: TravelState) -> str:
        """Determine if we should synthesize or finalize"""
        if state["workflow_status"] == WorkflowStatus.SYNTHESIZING:
            return "synthesize"
        return "finalize"
    
    async def _synthesize_node(self, state: TravelState) -> TravelState:
        """Synthesize final itinerary from all agent data"""
        self.logger.info("🎨 Synthesizing final itinerary")
        
        # Dispatch request to itinerary agent
        request = MessageFactory.create_itinerary_request(
            session_id=state["session_id"],
            travel_state=dict(state),
            timeout_ms=settings.timeout_itinerary
        )
        
        # Update agent status
        state = update_agent_status(state, "itinerary", AgentStatus.PROCESSING)
        
        # Publish to itinerary request channel
        channel = RedisChannels.ITINERARY_REQUEST
        await self.redis_client.publish(channel, request.dict())
        
        # Wait for itinerary response
        response_channel = RedisChannels.get_response_channel(
            "itinerary",
            state["session_id"]
        )
        
        response_data = await self._wait_for_single_response(
            response_channel,
            timeout=settings.timeout_itinerary / 1000
        )
        
        if response_data and response_data.get("success"):
            data = response_data.get("data", {})
            state["itinerary_data"] = data.get("itinerary_days", [])
            state["final_itinerary"] = data.get("final_itinerary_text", "")
            state["itinerary_complete"] = True
            state = update_agent_status(state, "itinerary", AgentStatus.COMPLETED)
            self.logger.info("✅ Itinerary synthesis completed")
        else:
            error = response_data.get("error", "Unknown error") if response_data else "Timeout"
            state = update_agent_status(
                state, 
                "itinerary", 
                AgentStatus.FAILED,
                error_message=error
            )
            self.logger.error(f"❌ Itinerary synthesis failed: {error}")
        
        # Update state in Redis
        await self.redis_client.set_state(state["session_id"], dict(state))
        
        return state
    
    async def _wait_for_single_response(
        self,
        channel: str,
        timeout: float
    ) -> Optional[Dict[str, Any]]:
        """Wait for a single response from a channel"""
        
        response_future = asyncio.Future()
        
        async def handler(data):
            if not response_future.done():
                response_future.set_result(data)
        
        subscription_id = await self.redis_client.subscribe(channel, handler)
        
        try:
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            return None
        finally:
            await self.redis_client.unsubscribe(subscription_id)
    
    async def _finalize_node(self, state: TravelState) -> TravelState:
        """Finalize the workflow and prepare response"""
        self.logger.info("🎯 Finalizing workflow")
        
        # Create trip summary
        completed_agents = state["completed_agents"]
        failed_agents = state["failed_agents"]
        
        if state["itinerary_complete"]:
            state["workflow_status"] = WorkflowStatus.COMPLETED
            state["trip_summary"] = (
                f"Travel plan completed successfully! "
                f"Generated itinerary with data from {completed_agents} agents."
            )
        elif completed_agents > 0:
            state["workflow_status"] = WorkflowStatus.PARTIAL
            state["trip_summary"] = (
                f"Travel plan partially completed. "
                f"Data available from {completed_agents} agents. "
                f"{failed_agents} agents failed or timed out."
            )
        else:
            state["workflow_status"] = WorkflowStatus.FAILED
            state["trip_summary"] = (
                "Travel plan could not be completed. "
                "All agents failed or timed out."
            )
        
        state["messages"].append(state["trip_summary"])
        
        # Final state update to Redis
        await self.redis_client.set_state(
            state["session_id"], 
            dict(state),
            ttl=7200  # Keep final state for 2 hours
        )
        
        self.logger.info(f"🎉 Workflow completed - Status: {state['workflow_status']}")
        
        return state
    
    # ==================== PUBLIC INTERFACE ====================
    
    async def plan_trip(
        self,
        destination: str,
        origin: str,
        travel_dates: List[str],
        travelers_count: int = 1,
        budget_range: Optional[str] = None,
        user_preferences: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> TravelState:
        """
        Plan a trip using the orchestrated agent workflow
        
        Args:
            destination: Destination city/location
            origin: Origin city/location
            travel_dates: List of travel dates (YYYY-MM-DD format)
            travelers_count: Number of travelers
            budget_range: Budget range (e.g., "$1000-2000")
            user_preferences: User preferences dict
            session_id: Optional session ID for resuming
            
        Returns:
            Final TravelState with all results
        """
        
        # Connect to Redis
        await self.redis_client.connect()
        
        try:
            # Create or resume state
            if session_id:
                existing_state = await self.redis_client.get_state(session_id)
                if existing_state:
                    self.logger.info(f"Resuming session: {session_id}")
                    initial_state = existing_state
                else:
                    self.logger.warning(f"Session {session_id} not found, creating new")
                    initial_state = create_initial_state(
                        destination=destination,
                        origin=origin,
                        travel_dates=travel_dates,
                        travelers_count=travelers_count,
                        budget_range=budget_range,
                        session_id=session_id
                    )
            else:
                initial_state = create_initial_state(
                    destination=destination,
                    origin=origin,
                    travel_dates=travel_dates,
                    travelers_count=travelers_count,
                    budget_range=budget_range
                )
            
            if user_preferences:
                from app.core.state import UserPreferences
                prefs = UserPreferences(**user_preferences)
                initial_state["user_preferences"] = prefs.dict()
            
            self.logger.info(
                f"🎪 Starting travel planning workflow\n"
                f"   Session: {initial_state['session_id']}\n"
                f"   Destination: {destination}\n"
                f"   Dates: {', '.join(travel_dates)}"
            )
            
            # Run the workflow
            config = {"configurable": {"thread_id": initial_state["session_id"]}}
            final_state = await self.graph.ainvoke(initial_state, config)
            
            return final_state
            
        except Exception as e:
            self.logger.error(f"Workflow failed: {str(e)}", exc_info=True)
            raise
    
    async def get_session_state(self, session_id: str) -> Optional[TravelState]:
        """Get state for a session"""
        return await self.redis_client.get_state(session_id)
    
    async def cancel_session(self, session_id: str):
        """Cancel an ongoing session"""
        self.logger.info(f"Cancelling session: {session_id}")
        
        # Publish cancel message
        cancel_msg = MessageFactory.create_cancel(
            session_id=session_id,
            agent=AgentType.ORCHESTRATOR,
            reason="User cancelled"
        )
        
        cancel_channel = RedisChannels.CANCEL.format(session_id=session_id)
        await self.redis_client.publish(cancel_channel, cancel_msg.dict())
        
        # Delete state
        await self.redis_client.delete_state(session_id)