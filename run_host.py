import uvicorn
import sys
import os

# Add the current directory to sys.path so we can import urp
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("Starting URP Independent Hosting Framework...")
    print("Access the Web Console at http://localhost:8000")
    
    # Run the FastAPI app using uvicorn
    uvicorn.run("examples.web_server:app", host="0.0.0.0", port=8000, reload=True)
