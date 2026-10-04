from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_teacherinvitation'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='email_verified',
            # default=True so existing rows backfill as verified; RegisterView
            # explicitly sets False for new signups.
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='email_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
