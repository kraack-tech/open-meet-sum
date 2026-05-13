# Open Meet Sum 👋

![GitHub stars](https://img.shields.io/github/stars/kraack-tech/open-meet-sum?style=social)
![GitHub forks](https://img.shields.io/github/forks/kraack-tech/open-meet-sum?style=social)
[![](https://img.shields.io/static/v1?label=Sponsor&message=%E2%9D%A4&logo=GitHub&color=%23fe8e86)](https://github.com/sponsors/kraack-tech)
![Open Meet Sum](ui.png)

**Open Meet Sum is an AI meeting assistant that automatically transcribes, summarizes, and analyses audio with human-in-the-loop collaboration AI-powered insights.** It's a self-hosted solution, supporting both local, model API endpoints and built-in transcription engines.

## ✨ Key Features

- 🎙️ **Real-time Transcription** - Automatic speech-to-text with built-in Whisper (small, mid, large)
- 🎯 **AI Summarization** - Generate smart summaries with bullet points and key takeaways  
- 👤 **Speaker Recognition** - Automatically identify and track speakers in meetings
- 📝 **Live Meeting Support** - Join meetings with real-time transcription and processing
- 🔐 **Secure & Private** - JWT authentication, PostgreSQL storage, fully self-hosted
- 👥 **Multi-user & Teams** - Team-based meeting organization and user management
- 💾 **Persistent Storage** - Database-backed persistent storage for all your meetings
- 📊 **Admin Dashboard** - Full administration interface for users and settings
- 🚀 **REST API** - Complete API for integration with other tools
- 🐳 **Docker Ready** - Single-image deployment (local test -> registry -> container app)

## 🚀 Install

### Local Development

**Terminal 1 - Backend:**
```bash
# Create a virtual environment 
conda create -n meetSum python=3.11
conda activate meetSum
pip install -r requirements.txt

# Create a file for environment variables
cd backend
cp .env.example .env

#  Run
sh run.sh
```

**Terminal 2 - Frontend (new terminal):**
```bash
conda activate meetSum
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

> [!NOTE]
> Run in two separate terminals - one for backend, one for frontend. Keep both running.


### Docker (Single Image)

```bash
git clone https://github.com/kraack-tech/open-meet-sum.git
cd open-meet-sum
docker build -t open-meet-sum:local .
```

Run container with your external PostgreSQL:

```bash
docker run --rm -p 8001:8001 \
	-e DATABASE_URL='postgresql://postgres:password@host.docker.internal:8000/meetsum' \
	-e JWT_SECRET_KEY='super-secret-key' \
	open-meet-sum:local
```

Optional: persist model cache to avoid large re-downloads:

```bash
docker volume create meetsum-model-cache
docker run --rm -p 8001:8001 \
	-e DATABASE_URL='postgresql://postgres:password@host.docker.internal:8000/meetsum' \
	-e JWT_SECRET_KEY='super-secret-key' \
	-e XDG_CACHE_HOME='/home/appuser/.cache' \
	-e HF_HOME='/home/appuser/.cache/huggingface' \
	-v meetsum-model-cache:/home/appuser/.cache \
	open-meet-sum:local
```

Access at [http://localhost:8001](http://localhost:8001)
API docs at [http://localhost:8001/docs](http://localhost:8001/docs)

> [!NOTE]
>NOTE: This can take up to about 3 minutes on first run due to downloading the local models.


## ⚙️ Configuration
### Environment Variables

**Backend (.env):**
```bash
DATABASE_URL=postgresql://postgres:password@localhost:5432/meetsum
JWT_SECRET_KEY=your-secret-key
CORS_ORIGINS=http://localhost:5173,http://localhost:8001
```

**Frontend (.env):**
```bash
VITE_API_URL=http://localhost:8001
```

## 🤝 Contributing
We welcome contributions! Please:
1. Fork the repository
2. Create a new branch: `git checkout -b feature/new-feature`
3. Make your changes
4. Commit: `git commit -m 'feat: add new feature'`
5. Push: `git push origin feature/new-feature`
6. Open a Pull Request

Made with ❤️ for better meetings

[⬆ Back to top](#open-meet-sum-)
