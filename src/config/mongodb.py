import logging
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from django.conf import settings

logger = logging.getLogger('django')

# suppress pymongo heartbeat/topology noise
for _noisy in ('pymongo', 'pymongo.serverMonitor', 'pymongo.topology', 'pymongo.connection', 'pymongo.command'):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        _client = MongoClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=5000,
        )
        try:
            _client.admin.command('ping')
        except ConnectionFailure as e:
            logger.error(f"MongoDB connection failed: {e}")
            raise
        _db = _client[settings.MONGODB_DB_NAME]
        _db['content_structures'].create_index(
            [('type', 1), ('display_id', 1)],
            unique=True,
            background=True,
        )
        logger.info("MongoDB connected.")
    return _db
