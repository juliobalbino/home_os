from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("shopping", "0002_purchaseitem_shopping_list_item_and_more")]

    operations = [
        migrations.AddConstraint(
            model_name="purchaseitem",
            constraint=models.UniqueConstraint(
                condition=models.Q(shopping_list_item__isnull=False),
                fields=("shopping_list_item",),
                name="shopping_list_item_single_purchase",
            ),
        ),
    ]
