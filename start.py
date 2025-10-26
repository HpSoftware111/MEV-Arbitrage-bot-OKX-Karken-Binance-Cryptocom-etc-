"""
Startup script for MEV Bot
"""

import uvicorn
import logging
from database import create_tables

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    """Start the MEV Bot application"""
    logger.info("Starting MEV Bot - XRP Price Monitor")
    
    # Create database tables
    create_tables()
    logger.info("Database initialized")
    
    # Start FastAPI server
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info"
    )

if __name__ == "__main__":
    main()
