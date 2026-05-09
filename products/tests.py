from django.test import SimpleTestCase
from django.urls import reverse, resolve
from products import views

class TestUrls(SimpleTestCase):
    """Test URL patterns are working correctly"""
    
    def test_product_list_url(self):
        url = reverse('products:list')
        self.assertEqual(resolve(url).func, views.product_list)
    
    def test_product_detail_url(self):
        url = reverse('products:detail', args=['test-product'])
        self.assertEqual(resolve(url).func, views.product_detail)
    
    def test_category_url(self):
        url = reverse('products:category', args=['electronics'])
        self.assertEqual(resolve(url).func, views.category_view)
    
    def test_cart_url(self):
        url = reverse('products:cart')
        self.assertEqual(resolve(url).func, views.cart_view)
    
    def test_add_to_cart_url(self):
        url = reverse('products:add_to_cart', args=['test-product'])
        self.assertEqual(resolve(url).func, views.add_to_cart)
    
    def test_add_review_url(self):
        url = reverse('products:add_review', args=['test-product'])
        self.assertEqual(resolve(url).func, views.add_review)
    
    def test_ask_question_url(self):
        url = reverse('products:ask_question', args=['test-product'])
        self.assertEqual(resolve(url).func, views.ask_question)
    
    def test_answer_question_url(self):
        url = reverse('products:answer_question', args=[1])
        self.assertEqual(resolve(url).func, views.answer_question)
    
    def test_toggle_wishlist_url(self):
        url = reverse('products:toggle_wishlist', args=['test-product'])
        self.assertEqual(resolve(url).func, views.toggle_wishlist)
    
    def test_variant_details_api_url(self):
        url = reverse('products:variant_details', args=[1])
        self.assertEqual(resolve(url).func, views.get_variant_details)
    
    def test_quick_view_api_url(self):
        url = reverse('products:quick_view_api', args=[1])
        self.assertEqual(resolve(url).func, views.quick_view_api)
    
    def test_questions_api_url(self):
        url = reverse('products:questions_api', args=[1])
        self.assertEqual(resolve(url).func, views.get_question_api)
    
    def test_edit_question_url(self):
        url = reverse('products:edit_question', args=[1])
        self.assertEqual(resolve(url).func, views.edit_question)
    
    def test_delete_question_url(self):
        url = reverse('products:delete_question', args=[1])
        self.assertEqual(resolve(url).func, views.delete_question)
    
    def test_helpful_question_url(self):
        url = reverse('products:helpful_question', args=[1])
        self.assertEqual(resolve(url).func, views.helpful_question)
    
    def test_edit_answer_url(self):
        url = reverse('products:edit_answer', args=[1])
        self.assertEqual(resolve(url).func, views.edit_answer)
    
    def test_add_accessory_url(self):
        url = reverse('products:add_accessory', args=[1])
        self.assertEqual(resolve(url).func, views.add_accessory_to_cart)
    
    def test_cart_count_url(self):
        url = reverse('products:cart_count')
        self.assertEqual(resolve(url).func, views.cart_count)
    
    def test_checkout_url(self):
        url = reverse('products:checkout')
        self.assertEqual(resolve(url).func, views.checkout)
    
    def test_debug_colors_url(self):
        url = reverse('products:debug_colors', args=[1])
        self.assertEqual(resolve(url).func, views.debug_colors)