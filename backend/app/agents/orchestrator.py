import os
import traceback
from .utility_agents import init_agent_run, log_run_step
from .parser_agent import run_parser_agent
from .mapper_agent import run_mapper_agent
from .insights_agent import run_insights_agent
from .frontend_agent import run_frontend_agent

async def orchestrate_statement_processing(file_path: str, trigger_source: str) -> str:
    """Orchestrates the entire agentic bank statement processing pipeline.
    
    Args:
        file_path: The absolute path of the statement to process.
        trigger_source: Description of how the run was triggered (e.g. 'folder: Axis.pdf', 'email: Axis.pdf').
    Returns:
        The status ('completed', 'failed', or 'human_required').
    """
    # 1. Initialize the run log in the DB
    run_id = init_agent_run(f"{trigger_source} ({os.path.basename(file_path)})")
    
    try:
        # Step 1: Parse the statement (Super Agent 1)
        parse_success = await run_parser_agent(file_path, run_id)
        if not parse_success:
            # Either parsing failed or parser was not present (which triggers human email notification)
            log_run_step(run_id, "failed", "Parser execution stopped. Human notification sent.", "Parser missing or parse failed.")
            # Remove the unprocessed file from the directory so it doesn't loop trigger
            try:
                os.remove(file_path)
            except Exception:
                pass
            return "human_required"
            
        # Step 2: Categorize/Map transactions (Super Agent 2)
        await run_mapper_agent(run_id)
        
        # Step 3: Compute Insights and Correlations (Super Agent 3)
        await run_insights_agent(run_id)
        
        # Step 4: Finalize metrics and complete (Super Agent 4)
        await run_frontend_agent(run_id)
        
        # Clean up processed file
        try:
            os.remove(file_path)
        except Exception:
            pass
            
        return "completed"
        
    except Exception as e:
        error_msg = f"Orchestrator encountered error: {str(e)}"
        trace = traceback.format_exc()
        print(f"Agentic Pipeline Failure:\n{trace}")
        log_run_step(run_id, "failed", error_msg, trace)
        
        # Clean up file on failure as well to prevent loop triggers
        try:
            os.remove(file_path)
        except Exception:
            pass
            
        return "failed"
