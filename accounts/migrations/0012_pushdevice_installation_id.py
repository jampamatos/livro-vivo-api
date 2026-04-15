from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_alter_dataprivacyrequest_request_type_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pushdevice',
            name='installation_id',
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
    ]
