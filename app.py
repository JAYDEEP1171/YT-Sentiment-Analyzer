import os
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from urllib.parse import urlparse, parse_qs
from textblob import TextBlob
from googleapiclient.discovery import build
from wordcloud import WordCloud
import matplotlib.pyplot as plt
from collections import Counter
import requests
from pathlib import Path

# --- Config ---
BASEDIR = Path(__file__).resolve().parent  # Base directory of the project
STATIC_DIR = BASEDIR / "static"  # Static files directory
WORDCLOUD_DIR = STATIC_DIR / "wordclouds"  # Directory for wordcloud images
CHART_DIR = STATIC_DIR / "charts"  # Directory for pie chart images
THUMB_DIR = STATIC_DIR / "thumbs"  # Directory for video thumbnail images

# Create directories if they don't exist
for d in [WORDCLOUD_DIR, CHART_DIR, THUMB_DIR]:
    d.mkdir(exist_ok=True, parents=True)

# YouTube API Key (ideally should be stored in environment variables)
API_KEY = os.getenv('YOUTUBE_API_KEY', "AIzaSyBBdsWdGANyUZDyn6v1yG8m7Tchx99fAdI")

# Initialize Flask app
app = Flask(__name__, static_folder="static")


# --- Helper Functions ---

def extract_video_id(url):
    """
    Extracts the video ID from a YouTube video URL.

    Args:
        url (str): The URL of the YouTube video.

    Returns:
        str: The extracted video ID, or None if the URL is invalid.
    """
    try:
        query = urlparse(url).query  # Parse the query part of the URL
        return parse_qs(query).get('v', [None])[0]  # Extract 'v' parameter as the video ID
    except Exception:
        return None


def get_comments(video_id, api_key, max_results=300):
    """
    Fetches comments from a YouTube video using YouTube Data API v3.

    Args:
        video_id (str): The YouTube video ID.
        api_key (str): The API key for accessing the YouTube Data API.
        max_results (int): The maximum number of comments to fetch.

    Returns:
        List[str]: A list of the comments from the video.
    """
    youtube = build('youtube', 'v3', developerKey=api_key)
    comments = []

    # Fetching comment threads
    req = youtube.commentThreads().list(
        part='snippet', videoId=video_id, maxResults=100, textFormat='plainText'
    )
    res = req.execute()

    # Extract comments from response
    for item in res.get('items', []):
        comment = item['snippet']['topLevelComment']['snippet']['textDisplay']
        comments.append(comment)

    return comments[:max_results]  # Return only the first 'max_results' comments


def get_video_details(video_id, api_key):
    """
    Fetches details (title and thumbnail URL) of a YouTube video.

    Args:
        video_id (str): The YouTube video ID.
        api_key (str): The API key for accessing the YouTube Data API.

    Returns:
        tuple: A tuple containing the video title and thumbnail URL.
    """
    youtube = build('youtube', 'v3', developerKey=api_key)
    req = youtube.videos().list(part="snippet", id=video_id)
    res = req.execute()

    if res["items"]:
        snippet = res["items"][0]["snippet"]
        title = snippet.get("title", "Unknown title")
        thumb_url = snippet["thumbnails"]["high"]["url"]
        return title, thumb_url
    else:
        return "Unknown Title", ""  # Return default title if video details are not found


def download_thumbnail(url, save_path):
    """
    Downloads the video thumbnail and saves it to the specified path.

    Args:
        url (str): The URL of the thumbnail image.
        save_path (str): The path where the thumbnail should be saved.

    Returns:
        str: The path to the saved thumbnail, or None if the download fails.
    """
    try:
        r = requests.get(url, stream=True)
        if r.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(r.content)
            return save_path
    except Exception:
        pass
    return None


def analyze_sentiment(comment):
    """
    Analyzes the sentiment of a given comment using TextBlob.

    Args:
        comment (str): The comment text to analyze.

    Returns:
        str: The sentiment of the comment ('Positive', 'Negative', or 'Neutral').
    """
    polarity = TextBlob(comment).sentiment.polarity  # Get polarity of sentiment
    if polarity > 0:
        return "Positive"
    elif polarity < 0:
        return "Negative"
    else:
        return "Neutral"


def generate_wordcloud(texts, label, save_dir):
    """
    Generates a word cloud from the given list of texts.

    Args:
        texts (list): A list of texts (comments).
        label (str): Label for the word cloud (e.g., 'Positive', 'Negative').
        save_dir (Path): Directory to save the generated word cloud image.

    Returns:
        str: The relative file path of the saved word cloud image.
    """
    if not texts:
        return None
    text = " ".join(texts)  # Join all comments into a single text
    wordcloud = WordCloud(width=800, height=400, background_color='white').generate(text)
    file_path = save_dir / f'wordcloud_{label}.png'
    wordcloud.to_file(str(file_path))
    return f'wordclouds/wordcloud_{label}.png'  # Return the relative path


def generate_pie_chart(sentiments, save_dir):
    """
    Generates a pie chart showing the distribution of sentiments.

    Args:
        sentiments (list): A list of sentiment labels ('Positive', 'Negative', 'Neutral').
        save_dir (Path): Directory to save the generated pie chart image.

    Returns:
        str: The relative file path of the saved pie chart image.
    """
    data = Counter(sentiments)  # Count the occurrences of each sentiment
    for sent in ("Positive", "Negative", "Neutral"):
        data.setdefault(sent, 0)  # Ensure all sentiments have at least 0 count

    labels = list(data.keys())
    sizes = list(data.values())

    plt.figure(figsize=(4, 4))
    plt.pie(sizes, labels=labels, autopct='%1.1f%%', colors=["#22c55e", "#ef4444", "#a3a3a3"])
    plt.title("Sentiment Distribution")

    file_path = save_dir / 'sentiment_pie.png'
    plt.savefig(file_path, bbox_inches="tight", transparent=True)
    plt.close()

    return 'charts/sentiment_pie.png'  # Return the relative path


# --- Routes ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """
    The main route that handles the user input for YouTube video URL, processes the comments,
    and generates results including sentiment analysis and visualizations.

    Returns:
        Rendered HTML template with results or error message.
    """
    result, msg = None, None
    if request.method == 'POST':
        url = request.form.get('url', '')
        vid = extract_video_id(url)

        if not vid:
            msg = "Invalid YouTube URL."  # Error if the URL is invalid
        else:
            try:
                # Fetch comments and perform sentiment analysis
                comments = get_comments(vid, API_KEY, 300)
                sentiments = [analyze_sentiment(c) for c in comments]

                # Separate positive and negative comments
                pos_comments = [c for c, s in zip(comments, sentiments) if s == "Positive"]
                neg_comments = [c for c, s in zip(comments, sentiments) if s == "Negative"]

                # Fetch video details (title and thumbnail)
                title, thumb_url = get_video_details(vid, API_KEY)
                thumb_path = THUMB_DIR / f"{vid}.jpg"
                thumb_rel = f"thumbs/{vid}.jpg"

                # Download thumbnail image
                download_thumbnail(thumb_url, thumb_path)

                # Generate sentiment pie chart and word clouds
                pie_path = generate_pie_chart(sentiments, CHART_DIR)
                wc_pos = generate_wordcloud(pos_comments, "Positive", WORDCLOUD_DIR)
                wc_neg = generate_wordcloud(neg_comments, "Negative", WORDCLOUD_DIR)

                # Prepare results for rendering
                result = {
                    "video_title": title,
                    "video_url": url,
                    "thumb": thumb_rel,
                    "pie_chart": pie_path,
                    "wc_pos": wc_pos,
                    "wc_neg": wc_neg,
                    "sentiments": Counter(sentiments),
                    "comment_count": len(comments),
                }
            except Exception as e:
                msg = f"Error: {str(e)}"  # Handle any errors during the process

    return render_template('index.html', result=result, msg=msg)  # Render the main page with results or error


# Serve static (generated) images from folders
@app.route('/wordclouds/<path:filename>')
def wordclouds(filename):
    """
    Serves the generated word cloud image.
    """
    return send_from_directory(WORDCLOUD_DIR, filename)


@app.route('/charts/<path:filename>')
def charts(filename):
    """
    Serves the generated pie chart image.
    """
    return send_from_directory(CHART_DIR, filename)


@app.route('/thumbs/<path:filename>')
def thumbs(filename):
    """
    Serves the downloaded thumbnail image.
    """
    return send_from_directory(THUMB_DIR, filename)


# --- Error Handlers ---

@app.errorhandler(404)
def not_found(e):
    """
    Custom handler for 404 errors (Page Not Found).
    """
    return render_template('404.html'), 404


@app.errorhandler(Exception)
def handle_exception(e):
    """
    Generic error handler for any unhandled exceptions.
    """
    return render_template('error.html', detail=str(e)), 500


# --- Run the Flask App ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

