
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage, SystemMessage
from app.config.settings import settings
from app.core.state import TravelState
import logging


class BaseAgent(ABC):
    """Base class for all travel planning agents"""
    
    def __init__(self, name: str, role: str, expertise: str):
        self.name = name
        self.role = role
        self.expertise = expertise
        self.logger = logging.getLogger(f"agent.{name.lower()}")
        
        # Initialize the language model
        self.llm = ChatGoogleGenerativeAI(
            model=settings.model_name,
            google_api_key=settings.google_api_key,
            temperature=settings.temperature,
            max_output_tokens=settings.max_tokens
        )
    
    @abstractmethod
    async def process(self, state: TravelState) -> TravelState:
        """Process the travel state and return updated state"""
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent"""
        pass
    
    def create_messages(self, system_prompt: str, user_input: str):
        """Create message list for the LLM"""
        return [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_input)
        ]
    
    async def invoke_llm(self, system_prompt: str, user_input: str) -> str:
        """Invoke the language model with system and user prompts"""
        try:
            messages = self.create_messages(system_prompt, user_input)
            response = await self.llm.ainvoke(messages)
            return response.content
        except Exception as e:
            self.logger.error(f"LLM invocation failed: {str(e)}")
            raise e
    
    def log_action(self, action: str, details: Optional[str] = None):
        """Log agent actions"""
        log_msg = f"{self.name} - {action}"
        if details:
            log_msg += f": {details}"
        self.logger.info(log_msg)
    
    def log_error(self, error: str, details: Optional[str] = None):
        """Log agent errors"""
        log_msg = f"{self.name} - ERROR: {error}"
        if details:
            log_msg += f": {details}"
        self.logger.error(log_msg)
    
    def add_message_to_state(self, state: TravelState, message: str):
        """Add a message to the state"""
        state["messages"].append(f"[{self.name}] {message}")
    
    def add_error_to_state(self, state: TravelState, error: str):
        """Add an error to the state"""
        state["errors"].append(f"[{self.name}] {error}")
        self.log_error(error)
    
    def format_location_context(self, state: TravelState) -> str:
        """Format location context for prompts"""
        return f"""
        Origin: {state['origin']}
        Destination: {state['destination']}
        Travel Dates: {', '.join(state['travel_dates'])}
        Number of Travelers: {state['travelers_count']}
        Budget Range: {state.get('budget_range', 'Not specified')}
        """
    
    def should_process(self, state: TravelState) -> bool:
        """Determine if this agent should process based on state"""
        return True  # Default implementation, override as needed