extends Area2D
class_name CoinCollectible

@export var value: int = 1

func _ready():
    body_entered.connect(_on_body_entered)

func _on_body_entered(body):
    if body.has_method("add_coins"):
        body.add_coins(value)
    elif "coins" in body:
        body.coins += value

    queue_free()
