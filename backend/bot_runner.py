from backend.bot import create_application
# Note: python-telegram-bot v21 provides a blocking run_polling method
def main():
    app = create_application()
    # Blocking call; handles signals and idles
    app.run_polling()
if __name__ == "__main__":
    main()
