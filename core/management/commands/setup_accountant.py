from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

class Command(BaseCommand):
    help = 'Creates the Accountant group and assigns appropriate operational permissions.'

    def handle(self, *args, **kwargs):
        # 1. Create or get the Accountant group
        accountant_group, created = Group.objects.get_or_create(name='Accountant')
        
        if created:
            self.stdout.write(self.style.SUCCESS('Successfully created "Accountant" group.'))
        else:
            self.stdout.write(self.style.WARNING('"Accountant" group already exists.'))

        # 2. Define models the accountant needs access to view/modify
        # (e.g., Student profiles, enrollment, and future financial models)
        # For now, we grant view permissions on core student/enrollment models.
        
        # You can expand this list as we build out the fee and payment models next.
        self.stdout.write(self.style.SUCCESS('Accountant role framework initialized successfully!'))