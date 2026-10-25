class SpeechToTextError(Exception):
    """Custom exception for speech-to-text  converation"""

    pass


class TextToSpeechError(Exception):
    """Custom exception  for text-to-speech conversation"""

    pass


class TextToImageError(Exception):
    """Custom exception for text-to-image generations errors."""

    pass


class ImageToTextError(Exception):
    """Custom exception for image-to-text conversation errors"""

    pass