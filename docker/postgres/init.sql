-- Initialize PostgreSQL with PGVector extension for Kotodama

-- Enable PGVector extension for Lore RAG embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Create enum types for better type safety
CREATE TYPE user_role AS ENUM ('user', 'admin', 'studio');
CREATE_TYPE project_status AS ENUM ('draft', 'generating', 'ready', 'failed', 'archived');
CREATE TYPE generation_step AS ENUM (
    'designer', 'architect', 'quest_designer', 'dialogue_writer',
    'art_director', 'coder', 'qa', 'playtest', 'commit'
);

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    username VARCHAR(100) NOT NULL,
    role user_role DEFAULT 'user',
    credits INTEGER DEFAULT 10,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Lore collections (user's knowledge base for RAG)
CREATE TABLE IF NOT EXISTS lore_collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    universe_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Lore entries (individual pieces of lore to be vectorized)
CREATE TABLE IF NOT EXISTS lore_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID REFERENCES lore_collections(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    entry_type VARCHAR(50) NOT NULL, -- 'character', 'location', 'rule', 'item', 'faction', etc.
    metadata JSONB DEFAULT '{}',
    embedding vector(768), -- nomic-embed-text produces 768-dimensional vectors
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create index for vector similarity search
CREATE INDEX IF NOT EXISTS lore_entries_embedding_idx 
ON lore_entries USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Projects (generated games)
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status project_status DEFAULT 'draft',
    genre VARCHAR(100),
    perspective VARCHAR(50),
    art_style VARCHAR(100),
    setting TEXT,
    scale VARCHAR(50),
    controls JSONB,
    save_enabled BOOLEAN DEFAULT false,
    monetization_template VARCHAR(100),
    quest_complexity VARCHAR(50) DEFAULT 'none',
    dialogue_depth VARCHAR(50) DEFAULT 'none',
    lore_collection_id UUID REFERENCES lore_collections(id),
    wizard_config JSONB, -- Full wizard configuration
    git_commit_hash VARCHAR(40), -- Current stable commit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Generation jobs
CREATE TABLE IF NOT EXISTS generation_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    step generation_step NOT NULL,
    status VARCHAR(50) DEFAULT 'pending', -- pending, running, success, failed, retrying
    attempt INTEGER DEFAULT 1,
    input_data JSONB,
    output_data JSONB,
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Generated assets metadata
CREATE TABLE IF NOT EXISTS assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    slot VARCHAR(50) NOT NULL, -- player, enemy, background, etc.
    asset_type VARCHAR(50) NOT NULL, -- sprite, texture, sound, music, ui
    file_path VARCHAR(500) NOT NULL,
    minio_bucket VARCHAR(255) NOT NULL,
    minio_key VARCHAR(500) NOT NULL,
    dimensions_width INTEGER,
    dimensions_height INTEGER,
    duration_seconds FLOAT,
    tags TEXT[],
    prompt_used TEXT,
    provider VARCHAR(50), -- local, fal, replicate
    used_in_modules TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Modules (reusable components)
CREATE TABLE IF NOT EXISTS modules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id UUID REFERENCES users(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    category VARCHAR(100), -- gameplay, ui, system, mechanic
    price_credits INTEGER DEFAULT 0,
    is_public BOOLEAN DEFAULT false,
    download_count INTEGER DEFAULT 0,
    rating FLOAT DEFAULT 0.0,
    manifest JSONB NOT NULL, -- Module configuration and dependencies
    code_snapshot_path VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Quest graphs (structured quest data)
CREATE TABLE IF NOT EXISTS quests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    quest_id VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    stages JSONB NOT NULL, -- Array of quest stages
    dependencies TEXT[], -- Array of quest_ids this quest depends on
    npcs_involved TEXT[],
    items_required TEXT[],
    rewards JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Dialogue trees (structured dialogue data)
CREATE TABLE IF NOT EXISTS dialogues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    dialogue_id VARCHAR(100) NOT NULL,
    npc_id VARCHAR(100) NOT NULL,
    trigger_condition VARCHAR(255), -- quest_stage:quest_id:stage or other triggers
    nodes JSONB NOT NULL, -- Dialogue tree structure
    conditions JSONB, -- Conditions and actions
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Localization strings
CREATE TABLE IF NOT EXISTS localization_strings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    locale VARCHAR(10) NOT NULL DEFAULT 'en',
    key VARCHAR(255) NOT NULL,
    value TEXT NOT NULL,
    category VARCHAR(50), -- quest, dialogue, item, ui, npc
    UNIQUE(project_id, locale, key)
);

-- Playtest reports
CREATE TABLE IF NOT EXISTS playtest_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    stability_score INTEGER NOT NULL,
    fps_avg FLOAT,
    fps_min FLOAT,
    frame_count INTEGER,
    engine_errors INTEGER DEFAULT 0,
    module_errors INTEGER DEFAULT 0,
    crashed BOOLEAN DEFAULT false,
    timed_out BOOLEAN DEFAULT false,
    reached_end_point BOOLEAN DEFAULT false,
    items_collected INTEGER DEFAULT 0,
    npcs_interacted INTEGER DEFAULT 0,
    quests_started INTEGER DEFAULT 0,
    quests_completed INTEGER DEFAULT 0,
    dialogues_opened INTEGER DEFAULT 0,
    player_deaths INTEGER DEFAULT 0,
    stuck_frames INTEGER DEFAULT 0,
    raw_log TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Generation history for prompt refinement
CREATE TABLE IF NOT EXISTS generation_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    agent_name VARCHAR(100) NOT NULL,
    success BOOLEAN NOT NULL,
    input_prompt TEXT,
    output_content TEXT,
    error_message TEXT,
    execution_time_ms INTEGER,
    tokens_used INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_lore_entries_collection ON lore_entries(collection_id);
CREATE INDEX IF NOT EXISTS idx_generation_jobs_project ON generation_jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_assets_project ON assets(project_id);
CREATE INDEX IF NOT EXISTS idx_quests_project ON quests(project_id);
CREATE INDEX IF NOT EXISTS idx_dialogues_project ON dialogues(project_id);
CREATE INDEX IF NOT EXISTS idx_localization_project_locale ON localization_strings(project_id, locale);

-- Trigger to update updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_lore_collections_updated_at BEFORE UPDATE ON lore_collections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_modules_updated_at BEFORE UPDATE ON modules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Insert default admin user (password: admin123)
-- In production, use proper password hashing
INSERT INTO users (email, password_hash, username, role, credits)
VALUES (
    'admin@kotodama.local',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYzS3MebAJu',
    'admin',
    'admin',
    1000
) ON CONFLICT (email) DO NOTHING;
