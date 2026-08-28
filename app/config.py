from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str = "sqlite:///./date_rush.db"

    # Minimum number of same-gender users required in the queue before a
    # game room can be formed. The single opposite-gender user becomes the
    # challenger; the same-gender users become the audience.
    GAME_ROOM_THRESHOLD: int = 5

    # Number of questions asked per room (reserved for future use).
    QUESTIONS_PER_ROOM: int = 10

    # Number of public question rounds configured for each room.
    PUBLIC_QUESTION_ROUNDS: int = 3



settings = Settings()
