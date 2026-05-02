extends CanvasLayer

@onready var score_label: Label = $ScoreLabel
@onready var health_label: Label = $HealthLabel

func set_resources(resources: int) -> void:
    score_label.text = "Resources: %d" % resources

func set_health(current_health: int) -> void:
    health_label.text = "Base HP: %d" % current_health
