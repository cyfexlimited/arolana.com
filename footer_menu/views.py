from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from .models import FooterMenuCategory, FooterMenuItem

@staff_member_required
def manage_footer_menu(request):
    """Frontend management page for footer menu"""
    categories = FooterMenuCategory.objects.all().order_by('display_order')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_category':
            name = request.POST.get('name')
            icon = request.POST.get('icon', 'fas fa-link')
            description = request.POST.get('description', '')
            
            if name:
                FooterMenuCategory.objects.create(
                    name=name,
                    icon=icon,
                    description=description,
                    display_order=FooterMenuCategory.objects.count() + 1
                )
                messages.success(request, f'Category "{name}" added successfully!')
        
        elif action == 'edit_category':
            category_id = request.POST.get('category_id')
            category = get_object_or_404(FooterMenuCategory, id=category_id)
            category.name = request.POST.get('name', category.name)
            category.icon = request.POST.get('icon', category.icon)
            category.description = request.POST.get('description', category.description)
            category.display_order = request.POST.get('display_order', category.display_order)
            category.is_active = request.POST.get('is_active') == 'on'
            category.save()
            messages.success(request, f'Category "{category.name}" updated successfully!')
        
        elif action == 'delete_category':
            category_id = request.POST.get('category_id')
            category = get_object_or_404(FooterMenuCategory, id=category_id)
            category_name = category.name
            category.delete()
            messages.success(request, f'Category "{category_name}" deleted successfully!')
        
        elif action == 'add_item':
            category_id = request.POST.get('category_id')
            category = get_object_or_404(FooterMenuCategory, id=category_id)
            title = request.POST.get('title')
            url = request.POST.get('url')
            
            if title and url:
                FooterMenuItem.objects.create(
                    category=category,
                    title=title,
                    url=url,
                    display_order=category.items.count() + 1
                )
                messages.success(request, f'Menu item "{title}" added successfully!')
        
        elif action == 'edit_item':
            item_id = request.POST.get('item_id')
            item = get_object_or_404(FooterMenuItem, id=item_id)
            item.title = request.POST.get('title', item.title)
            item.url = request.POST.get('url', item.url)
            item.display_order = request.POST.get('display_order', item.display_order)
            item.is_active = request.POST.get('is_active') == 'on'
            item.open_in_new_tab = request.POST.get('open_in_new_tab') == 'on'
            item.save()
            messages.success(request, f'Menu item "{item.title}" updated successfully!')
        
        elif action == 'delete_item':
            item_id = request.POST.get('item_id')
            item = get_object_or_404(FooterMenuItem, id=item_id)
            item_title = item.title
            item.delete()
            messages.success(request, f'Menu item "{item_title}" deleted successfully!')
        
        return redirect('footer_menu:manage')
    
    context = {
        'categories': categories,
    }
    return render(request, 'footer_menu/manage.html', context)
