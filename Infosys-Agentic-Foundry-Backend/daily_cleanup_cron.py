import os
import sys
import logging
import argparse
from datetime import datetime
from pathlib import Path
import asyncio

current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from src.utils.langraph_tables_delete import LangGraphTablesCleaner
from src.utils.recycle_bin_manager import RecycleBinManager

def setup_logging():
    """Setup logging for cron execution"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger

def main():
    """Main function to run the cleanup"""
    parser = argparse.ArgumentParser(description='Daily LangGraph Tables Cleanup for Cron')
    parser.add_argument('--days', type=int, default=30, 
                       help='Number of days to keep (default: 30)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Run in dry-run mode (no actual deletion)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Limit number of batches for testing (default: no limit)')
    parser.add_argument('--quiet', action='store_true',
                       help='Reduce verbose logging (only show summary)')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging()
    
    try:
        logger.info("="*50)
        logger.info(f"Starting LangGraph cleanup - Days to keep: {args.days}, Dry run: {args.dry_run}")
        if args.limit:
            logger.info(f"Testing mode: Limited to {args.limit} batches")
        
        logger.info("Cascade deletion and restoration functionality is ENABLED")
        logger.info("  - Cascade deletion: Long-term table records will be deleted when checkpoints are deleted")
        logger.info("  - Cascade restoration: Long-term table records will be restored when checkpoints are restored")
        
        cleaner = LangGraphTablesCleaner(days_to_keep=args.days, dry_run=args.dry_run)
        if args.limit:
            cleaner.max_batches = args.limit
        if args.quiet:
            cleaner.quiet_mode = True
        stats = asyncio.run(cleaner.cleanup_old_data())
        logger.info("Main table cleanup completed successfully!")
        logger.info(f"Checkpoints processed: {stats.checkpoints_deleted}")
        logger.info(f"Checkpoint blobs processed: {stats.checkpoint_blobs_deleted}")
        logger.info(f"Total batches: {stats.total_batches}")
        
        # Run recycle bin cleanup (45 days retention)
        logger.info("Starting recycle bin cleanup...")
        recycle_manager = RecycleBinManager(days_to_keep_in_recycle=45, dry_run=args.dry_run) ###111
        recycle_deleted = asyncio.run(recycle_manager.cleanup_old_recycle_records())
        logger.info(f"Recycle bin cleanup completed - Deleted {recycle_deleted} old records")
        
        if args.dry_run:
            logger.info("DRY RUN MODE - No data was actually deleted")
            logger.info("  - Cascade operations were simulated and logged above")
        else:
            logger.info("DATA CLEANUP COMPLETED - Old records have been deleted from main tables and recycle bin")
            logger.info("  - Cascade deletion automatically handled related long-term table records")
        
        logger.info("="*50)
        
    except Exception as e:
        logger.error(f"Cleanup failed with error: {str(e)}")
        logger.error("="*50)
        sys.exit(1)

if __name__ == "__main__":
    main()