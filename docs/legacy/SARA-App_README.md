# SARA - Smart Artificial Review Assistance

[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Supabase](https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)](https://supabase.com/)
[![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white)](https://openai.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)


A comprehensive Streamlit-based application for automated systematic literature review using Large Language Models (LLMs). SARA provides a digital peer system that integrates existing LLMs to automate the screening process in literature reviews while maintaining transparency and reproducibility.

## Overview

SARA is designed to support researchers at ZHAW in conducting systematic literature reviews by:

- **Automating screening processes** using LLMs for title, abstract, and full-text analysis
- **Maintaining transparency** with detailed justifications for each decision
- **Ensuring reproducibility** through comprehensive logging and tracking
- **Following PRISMA guidelines** for systematic review methodology
- **Providing export capabilities** in multiple formats (CSV, JSON, RIS, BibTeX)
- **Real-time processing** with background worker architecture
- **Secure authentication** via Supabase Auth

## Quick Start

### Live Demo
**[Access the SARA Application](https://sara-zhaw.streamlit.app/)** - Register and start your systematic review today!


## Repository Structure

```
SARA-App/
├── 📂 core/                          # Core application logic
│   ├── review_worker.py             # Background task processor
│   ├── model_query.py               # LLM inference engine
│   ├── file_handler.py              # File processing utilities
│   ├── database.py                  # Database operations
│   ├── criteria_template.py         # Review criteria templates
│   ├── prompt_engine.py             # Prompt management
│   └── prompts_abstract.json        # LLM prompts configuration
│
├── 📂 pages/                        # Streamlit application pages
│   ├── home.py                      # Landing page with app overview
│   ├── login.py                     # User authentication
│   ├── criteria.py                  # Review criteria setup
│   ├── summary.py                   # Results summary and export
│   ├── settings.py                  # User settings and preferences
│   └── pw_reset.py                  # Password reset functionality
│
├── 📂 utils/                        # Utility modules
│   ├── login_manager.py             # Authentication management
│   ├── data_manager.py              # Data handling utilities
│   ├── data_handler.py              # Data processing helpers
│   ├── graphs.py                    # Visualization utilities
│   ├── helpers.py                   # General helper functions
│   └── secrets.py                   # Secrets management
│
├── 📂 background/                   # Background processing
│   └── worker.py                    # Background worker entry point
│
├── 📂 static/                       # Static assets
│   ├── ai_brain.json               # Lottie animation data
│   └── robot.json                  # Additional animations
│
├── 📂 data/                         # Sample data and exports
│   ├── citation-export.bib         # Sample bibliographic data
│   └── citation-export.ris         # Sample RIS format data
│
├── 📂 output/                       # Generated outputs
├── 📂 dev/                         # Development utilities
├── 📂 .streamlit/                  # Streamlit configuration
│   ├── config.toml                 # Streamlit settings
│   └── secrets.toml                # Application secrets
│
├── main.py                         # Main Streamlit application
├── requirements.txt                # Python dependencies
├── render.yaml                     # Deployment configuration
└── README.md                       # This file
```

## System Architecture

<div align="center">
  <img src="static/setup.png" alt="SARA System Setup" />
</div>

### Background Worker Tasks

The application uses a robust background worker system to process review tasks asynchronously:

#### 1. Task Polling
- **Function**: `fetch_pending_tasks()`
- **Purpose**: Continuously polls the database for new pending review tasks
- **Frequency**: Every 5 minutes (configurable)
- **Status**: Monitors task queue and prioritizes processing

#### 2. File Processing
- **Function**: `read_stored_csv()` / `read_stored_config()`
- **Purpose**: Retrieves uploaded CSV files and configuration data from Supabase storage
- **Storage**: Uses `review-tasks` bucket for input files
- **Validation**: Ensures file integrity and format compliance

#### 3. LLM Inference
- **Function**: `process_task()`
- **Purpose**: Executes LLM-based screening on abstracts using defined criteria
- **Models**: OpenAI GPT models (configurable)
- **Output**: Structured responses with inclusion/exclusion decisions and reasoning
- **Performance**: Optimized for accuracy and speed

#### 4. Results Management
- **Function**: `upload_results()` / `upload_raw_responses()`
- **Purpose**: Stores processed results and raw LLM responses
- **Storage**: 
  - Results → `review-results/results/`
  - Raw responses → `review-results/raw_responses/`
- **Backup**: Automatic versioning and backup

#### 5. Task Status Management
- **Functions**: `mark_task_complete()` / `mark_task_failed()`
- **Purpose**: Updates task status in database upon completion or failure
- **Notifications**: Real-time status updates to users

### User Interface Tasks

#### 1. Authentication Flow
- User login/signup via Supabase Auth
- Session management and security
- Password reset functionality
- Role-based access control

#### 2. Review Setup
- Define research objectives
- Configure inclusion/exclusion criteria
- Select review frameworks (PICOS, SPIDER, PECO, CUSTOM)
- Upload bibliographic data (RIS/BibTeX format)
- Template-based configuration

#### 3. Data Processing
- Automatic duplicate detection and removal
- File validation and preprocessing
- Error handling and recovery

#### 4. Results Analysis
- Interactive results visualization
- Filtering and sorting capabilities
- Export functionality (CSV, JSON, RIS, BibTeX)
- Statistical analysis and reporting

## Technology Stack

- **Frontend**: Streamlit (Python web framework)
- **Backend**: Python 3.11+
- **Database**: Supabase (PostgreSQL)
- **Authentication**: Supabase Auth
- **Storage**: Supabase Storage
- **AI/ML**: OpenAI GPT Models
- **Deployment**: Render.com/ cron
- **Background Processing**: Custom worker architecture

## Features

### Core Features
- **Automated Literature Screening** - AI-powered abstract analysis
- **Multi-format Support** - RIS, BibTeX, CSV import/export
- **Real-time Processing** - Background worker architecture
- **Transparent Decisions** - Detailed reasoning for each inclusion/exclusion
- **PRISMA Compliance** - Systematic review methodology
- **User Management** - Secure authentication and user profiles
- **Export Capabilities** - Multiple output formats

### Advanced Features
- **Duplicate Detection** - Automatic identification and removal
- **Visualization** - Interactive charts and graphs
- **Custom Criteria** - Flexible inclusion/exclusion rules
- **Analytics Dashboard** - Comprehensive review statistics (Todo)
- **Notifications** - Email notification with results

## Deployment

### Production Deployment

The application is deployed using a multi-service architecture with the following configuration:

#### Frontend Application
- **Platform**: Streamlit Cloud
- **Environment**: Python 3.11+
- **Auto-deploy**: Enabled on main branch
- **URL**: https://sara-zhaw.streamlit.app/
- **Build Command**: `pip install -r requirements.txt`
- **Start Command (localhost)**: `streamlit run main.py`

#### Background Worker Service
- **Platform**: Render.com (*ToDo.. for now use local*)
- **Service Type**: Worker
- **Environment**: Python 3.11+
- **Plan**: Free tier
- **Auto-deploy**: Enabled on main branch
- **Run Worker (lokal cron)**: `python run ./backround/worker.py`


#### Infrastructure Services
- **Database**: Supabase PostgreSQL
- **Authentication**: Supabase Auth
- **File Storage**: Supabase Storage
- **API Gateway**: Supabase REST API

#### Streamlit Secrets Configuration

The application uses a `.streamlit/secrets.toml` file for managing sensitive configuration. Create this file in your project root with the following content:


#### Deployment Process
1. **Code Push**: Changes to the main branch trigger automatic deployment
2. **Build Phase**: Dependencies are installed from `requirements.txt`
3. **Service Startup**: Both frontend and worker services start simultaneously
4. **Health Checks**: Services are monitored for successful startup
5. **Traffic Routing**: Requests are routed to the new deployment


---

**⚠️ Note**: This application is currently in development phase and should be used for demonstration purposes. All research results should be verified by human experts. The system is designed to assist researchers but not replace human judgment in systematic reviews.

